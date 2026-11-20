// kongre-ocr: taranmış PDF'i macOS Vision ile okur (OGE 278-T işlem raporları için).
// Kullanım: kongre-ocr dosya.pdf [ilk_sayfa]
// Çıktı: her satırda bir JSON: {"p": sayfa, "x": sol, "y": üst, "w": genişlik, "h": yükseklik, "t": metin}
// Koordinatlar sayfa boyutuna göre 0–1 aralığında, y yukarıdan aşağı.
import Foundation
import PDFKit
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("PDF açılamadı\n".data(using: .utf8)!)
    exit(1)
}
let first = args.count >= 3 ? max(0, (Int(args[2]) ?? 1) - 1) : 0

func render(_ page: PDFPage) -> CGImage? {
    // thumbnail, sayfayı ekranda göründüğü gibi çizer (/Rotate 90 ile yatay taranmış sayfalar dahil)
    let box = page.bounds(for: .mediaBox)
    let rotated = page.rotation % 180 != 0
    let scale: CGFloat = 2.5   // ~180 dpi: küçük tablo yazısı için yeterli
    let size = NSSize(width: (rotated ? box.height : box.width) * scale,
                      height: (rotated ? box.width : box.height) * scale)
    let img = page.thumbnail(of: size, for: .mediaBox)
    var rect = NSRect(origin: .zero, size: img.size)
    return img.cgImage(forProposedRect: &rect, context: nil, hints: nil)
}

let out = FileHandle.standardOutput
for i in first..<doc.pageCount {
    guard let page = doc.page(at: i), let img = render(page) else { continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false   // şirket adları ve sayılar düzeltilmesin
    req.recognitionLanguages = ["en-US"]
    try? VNImageRequestHandler(cgImage: img, options: [:]).perform([req])
    for obs in req.results ?? [] {
        guard let cand = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox   // sol alt köşe orijinli, 0–1
        let rec: [String: Any] = ["p": i + 1, "x": b.minX, "y": 1 - b.maxY, "w": b.width, "h": b.height, "t": cand.string]
        if let data = try? JSONSerialization.data(withJSONObject: rec), let s = String(data: data, encoding: .utf8) {
            out.write((s + "\n").data(using: .utf8)!)
        }
    }
}
