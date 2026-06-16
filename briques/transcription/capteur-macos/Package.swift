// swift-tools-version:6.0
import PackageDescription

// Capteur natif macOS (façon Granola, SANS pilote/bot) : capte la sortie audio système
// (les autres participants) + le micro (toi) via ScreenCaptureKit, mixe, et envoie le tout
// à la brique transcription (/notes). macOS 15+ requis (capture micro de ScreenCaptureKit).
let package = Package(
    name: "capteur",
    platforms: [.macOS(.v15)],
    targets: [
        .executableTarget(name: "capteur", path: "Sources/capteur")
    ]
)
