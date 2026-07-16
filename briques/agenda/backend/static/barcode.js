/* Générateur de code-barres vanilla, sans dépendance (S176).
   window.dessinerCodeBarres(svgEl, texte, format) — format "code128" | "ean13".
   Retourne true si dessiné, false si format non supporté / entrée invalide. */
(function () {
  "use strict";

  // Code128 : motifs (largeurs de barres/espaces), index 0..106 + stop.
  var C128 = [
    "212222","222122","222221","121223","121322","131222","122213","122312","132212","221213",
    "221312","231212","112232","122132","122231","113222","123122","123221","223211","221132",
    "221231","213212","223112","312131","311222","321122","321221","312212","322112","322211",
    "212123","212321","232121","111323","131123","131321","112313","132113","132311","211313",
    "231113","231311","112133","112331","132131","113123","113321","133121","313121","211331",
    "231131","213113","213311","213131","311123","311321","331121","312113","312311","332111",
    "314111","221411","431111","111224","111422","121124","121421","141122","141221","112214",
    "112412","122114","122411","142112","142211","241211","221114","413111","241112","134111",
    "111242","121142","121241","114212","124112","124211","411212","421112","421211","212141",
    "214121","412121","111143","111341","131141","114113","114311","411113","411311","113141",
    "114131","311141","411131","211412","211214","211232","2331112"
  ];

  function code128B(texte) {
    // Jeu B : ASCII 32..126 → valeur = code - 32.
    for (var t = 0; t < texte.length; t++) {
      var vv = texte.charCodeAt(t) - 32;
      if (vv < 0 || vv > 94) return null; // hors jeu B
    }
    var codes = [104]; // Start B
    var somme = 104;
    for (var j = 0; j < texte.length; j++) {
      var v = texte.charCodeAt(j) - 32;
      codes.push(v);
      somme += v * (j + 1);
    }
    codes.push(somme % 103); // checksum
    codes.push(106);         // Stop
    var motifs = codes.map(function (c) { return C128[c]; });
    return motifs.join("");  // suite de largeurs, barre puis espace en alternance
  }

  var EAN_L = ["0001101","0011001","0010011","0111101","0100011","0110001","0101111","0111011","0110111","0001011"];
  var EAN_G = ["0100111","0110011","0011011","0100001","0011101","0111001","0000101","0010001","0001001","0010111"];
  var EAN_R = ["1110010","1100110","1101100","1000010","1011100","1001110","1010000","1000100","1001000","1110100"];
  var EAN_PARITE = ["LLLLLL","LLGLGG","LLGGLG","LLGGGL","LGLLGG","LGGLLG","LGGGLL","LGLGLG","LGLGGL","LGGLGL"];

  function ean13Checksum(d12) {
    var s = 0;
    for (var i = 0; i < 12; i++) s += (i % 2 === 0 ? 1 : 3) * parseInt(d12[i], 10);
    return (10 - (s % 10)) % 10;
  }

  function ean13Bits(numero) {
    var digits = numero.replace(/\D/g, "");
    if (digits.length === 12) digits += String(ean13Checksum(digits));
    if (digits.length !== 13) return null;
    var first = parseInt(digits[0], 10);
    var parite = EAN_PARITE[first];
    var bits = "101"; // garde gauche
    for (var i = 1; i <= 6; i++) {
      var d = parseInt(digits[i], 10);
      bits += (parite[i - 1] === "L") ? EAN_L[d] : EAN_G[d];
    }
    bits += "01010"; // garde centrale
    for (var k = 7; k <= 12; k++) bits += EAN_R[parseInt(digits[k], 10)];
    bits += "101"; // garde droite
    return { bits: bits, digits: digits };
  }

  function svgRect(x, w) {
    return '<rect x="' + x + '" y="0" width="' + w + '" height="100" fill="#000"/>';
  }

  function dessinerDepuisLargeurs(svgEl, largeurs) {
    // largeurs = chaîne de chiffres ; alternance barre(noir)/espace à partir d'une barre.
    var x = 10, unite = 2, rects = "", noir = true, total = 10;
    for (var i = 0; i < largeurs.length; i++) {
      var w = parseInt(largeurs[i], 10) * unite;
      if (noir) rects += svgRect(x, w);
      x += w; total += w; noir = !noir;
    }
    total += 10;
    svgEl.setAttribute("viewBox", "0 0 " + total + " 100");
    svgEl.setAttribute("preserveAspectRatio", "none");
    svgEl.innerHTML = rects;
  }

  function dessinerDepuisBits(svgEl, bits) {
    var x = 10, unite = 2, rects = "", total = 10;
    for (var i = 0; i < bits.length; i++) {
      if (bits[i] === "1") rects += svgRect(x, unite);
      x += unite; total += unite;
    }
    total += 10;
    svgEl.setAttribute("viewBox", "0 0 " + total + " 100");
    svgEl.setAttribute("preserveAspectRatio", "none");
    svgEl.innerHTML = rects;
  }

  window.dessinerCodeBarres = function (svgEl, texte, format) {
    try {
      if (format === "ean13") {
        var r = ean13Bits(String(texte));
        if (!r) return false;
        dessinerDepuisBits(svgEl, r.bits);
        return true;
      }
      // défaut : Code128 jeu B
      var largeurs = code128B(String(texte));
      if (!largeurs) return false;
      dessinerDepuisLargeurs(svgEl, largeurs);
      return true;
    } catch (e) {
      return false;
    }
  };
})();
