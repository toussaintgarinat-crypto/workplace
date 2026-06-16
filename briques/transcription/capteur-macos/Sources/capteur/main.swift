// Capteur d'appel natif macOS — façon Granola, SANS bot ni pilote tiers.
//
// ScreenCaptureKit (macOS 15+) capte EN LOCAL :
//   • la sortie audio système  = la voix des AUTRES (Zoom/Meet/Teams, n'importe quelle app) ;
//   • le micro                  = TA voix.
// On mixe les deux et on envoie le WAV à la brique transcription (POST /notes), qui
// transcrit en local (Whisper) et produit les notes. Aucun robot ne rejoint l'appel.
//
// Permissions macOS au 1er lancement : « Enregistrement de l'écran » (pour l'audio système)
// et « Microphone ». Réglages → Confidentialité et sécurité.
//
// Usage :
//   capteur                       # enregistre jusqu'à Ctrl-C, puis transcrit + notes
//   capteur --secondes 30         # enregistre 30 s puis s'arrête tout seul
//   capteur --langue fr --ranger memoire
// Variables : BRIQUE_URL (défaut http://localhost:5980), TRANSCRIPTION_KEY (optionnel).

import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

// ── Réglages (env + arguments) — immuables, donc sûrs à partager ─
let env = ProcessInfo.processInfo.environment
let briqueURL = (env["BRIQUE_URL"] ?? "http://localhost:5980").trimmingCharacters(in: ["/"])
let apiKey = env["TRANSCRIPTION_KEY"]
let sampleRate = 48_000.0

func argValeur(_ nom: String) -> String? {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: nom), i + 1 < a.count { return a[i + 1] }
    return nil
}
let dureeMax = argValeur("--secondes").flatMap { Double($0) }
let langue = argValeur("--langue")
let ranger = argValeur("--ranger")           // memoire | dossier (optionnel)
let dossier = argValeur("--dossier")

func journal(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }
func erreurEtSortie(_ msg: String) -> Never { journal("Erreur : \(msg)"); exit(1) }

// ── Capteur : tout l'état est confiné dans cette classe, sérialisé par `accQueue`.
//    `@unchecked Sendable` car on garantit l'accès via la file (les callbacks SCKit sont
//    nonisolated ; on ne touche aux tableaux que dans accQueue.sync). ──
final class Capteur: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let accQueue = DispatchQueue(label: "capteur.acc")
    private var sysSamples = [Float]()
    private var micSamples = [Float]()
    private var flux: SCStream?
    private var arrete = false

    // — Réception des échantillons —
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard sampleBuffer.isValid else { return }
        switch type {
        case .audio:      ajouter(sampleBuffer, mic: false)
        case .microphone: ajouter(sampleBuffer, mic: true)
        default: break
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        journal("Flux interrompu : \(error.localizedDescription)")
    }

    private func ajouter(_ sb: CMSampleBuffer, mic: Bool) {
        guard let fd = sb.formatDescription,
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fd),
              let format = AVAudioFormat(streamDescription: asbd) else { return }
        let frames = AVAudioFrameCount(CMSampleBufferGetNumSamples(sb))
        guard frames > 0,
              let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return }
        pcm.frameLength = frames
        let st = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sb, at: 0, frameCount: Int32(frames), into: pcm.mutableAudioBufferList)
        guard st == noErr, format.commonFormat == .pcmFormatFloat32,
              let ch = pcm.floatChannelData else { return }

        let n = Int(frames)
        let canaux = Int(format.channelCount)
        var mono = [Float](repeating: 0, count: n)
        if format.isInterleaved {
            let p = ch[0]
            for i in 0..<n {
                var s: Float = 0
                for c in 0..<canaux { s += p[i * canaux + c] }
                mono[i] = s / Float(canaux)
            }
        } else {
            for i in 0..<n {
                var s: Float = 0
                for c in 0..<canaux { s += ch[c][i] }
                mono[i] = s / Float(canaux)
            }
        }
        accQueue.sync {
            if mic { micSamples.append(contentsOf: mono) } else { sysSamples.append(contentsOf: mono) }
        }
    }

    // — Démarrage —
    func demarrer() async throws {
        let contenu = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: true)
        guard let ecran = contenu.displays.first else {
            throw NSError(domain: "capteur", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Aucun écran détecté."])
        }
        let filtre = SCContentFilter(display: ecran, excludingWindows: [])

        let config = SCStreamConfiguration()
        config.capturesAudio = true                  // sortie système (les autres)
        config.excludesCurrentProcessAudio = true    // ne pas se capter soi-même
        config.sampleRate = Int(sampleRate)
        config.channelCount = 2
        config.captureMicrophone = true              // micro (toi) — macOS 15+
        config.width = 2; config.height = 2          // vidéo minimale (inutilisée)
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)

        let s = SCStream(filter: filtre, configuration: config, delegate: self)
        try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: accQueue)
        try s.addStreamOutput(self, type: .microphone, sampleHandlerQueue: accQueue)
        try await s.startCapture()
        flux = s
        journal("🎙️  Capture en cours (système + micro). Ctrl-C pour arrêter.")
    }

    // — Arrêt → mixage → WAV → envoi —
    func arreterEtEnvoyer() {
        let dejaArrete: Bool = accQueue.sync { let a = arrete; arrete = true; return a }
        if dejaArrete { return }
        Task {
            try? await flux?.stopCapture()
            let (sys, mic) = accQueue.sync { (sysSamples, micSamples) }
            let wav = Self.mixerEnWav(sys: sys, mic: mic)
            if wav.count <= 44 {
                erreurEtSortie("Aucun audio capté (permissions écran/micro accordées ?).")
            }
            journal("⏳ Transcription + notes…")
            Self.envoyer(wav)
        }
    }

    static func mixerEnWav(sys: [Float], mic: [Float]) -> Data {
        let n = max(sys.count, mic.count)
        var pcm = Data(capacity: n * 2)
        for i in 0..<n {
            let a = i < sys.count ? sys[i] : 0
            let b = i < mic.count ? mic[i] : 0
            var v = a + b
            if v > 1 { v = 1 }; if v < -1 { v = -1 }
            var e = Int16(v * 32_767).littleEndian
            withUnsafeBytes(of: &e) { pcm.append(contentsOf: $0) }
        }
        return enteteWav(pcm: pcm, taux: Int(sampleRate), canaux: 1, bits: 16)
    }

    static func enteteWav(pcm: Data, taux: Int, canaux: Int, bits: Int) -> Data {
        var d = Data()
        func u32(_ v: Int) { var x = UInt32(v).littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        func u16(_ v: Int) { var x = UInt16(v).littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        let octets = bits / 8
        let debit = taux * canaux * octets
        d.append(contentsOf: Array("RIFF".utf8)); u32(36 + pcm.count)
        d.append(contentsOf: Array("WAVE".utf8))
        d.append(contentsOf: Array("fmt ".utf8)); u32(16); u16(1); u16(canaux)
        u32(taux); u32(debit); u16(canaux * octets); u16(bits)
        d.append(contentsOf: Array("data".utf8)); u32(pcm.count)
        d.append(pcm)
        return d
    }

    static func envoyer(_ wav: Data) {
        guard let url = URL(string: "\(briqueURL)/notes") else { erreurEtSortie("URL invalide.") }
        let frontiere = "----capteur\(UUID().uuidString)"
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 600
        req.setValue("multipart/form-data; boundary=\(frontiere)", forHTTPHeaderField: "Content-Type")
        if let k = apiKey, !k.isEmpty { req.setValue(k, forHTTPHeaderField: "X-API-Key") }

        var corps = Data()
        func champ(_ nom: String, _ valeur: String) {
            corps.append("--\(frontiere)\r\n".data(using: .utf8)!)
            corps.append("Content-Disposition: form-data; name=\"\(nom)\"\r\n\r\n".data(using: .utf8)!)
            corps.append("\(valeur)\r\n".data(using: .utf8)!)
        }
        if let l = langue { champ("langue", l) }
        if let r = ranger { champ("destination", r) }
        if let dd = dossier { champ("dossier", dd) }
        corps.append("--\(frontiere)\r\n".data(using: .utf8)!)
        corps.append("Content-Disposition: form-data; name=\"fichier\"; filename=\"appel.wav\"\r\n"
            .data(using: .utf8)!)
        corps.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        corps.append(wav)
        corps.append("\r\n--\(frontiere)--\r\n".data(using: .utf8)!)

        let sem = DispatchSemaphore(value: 0)
        URLSession.shared.uploadTask(with: req, from: corps) { data, _, err in
            if let err = err { journal("Envoi échoué : \(err.localizedDescription)"); exit(1) }
            if let data = data, let s = String(data: data, encoding: .utf8) { print(s) }
            sem.signal()
        }.resume()
        sem.wait()
        exit(0)
    }
}

// ── Boucle principale ────────────────────────────────────────────
let capteur = Capteur()

signal(SIGINT, SIG_IGN)
let sig = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
sig.setEventHandler { capteur.arreterEtEnvoyer() }
sig.resume()

if let d = dureeMax {
    DispatchQueue.main.asyncAfter(deadline: .now() + d) { capteur.arreterEtEnvoyer() }
}

Task {
    do { try await capteur.demarrer() }
    catch { erreurEtSortie(error.localizedDescription) }
}

dispatchMain()
