import Foundation
import PDFKit
import AppKit
import Vision

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data(message.utf8)); exit(1)
}
guard CommandLine.arguments.count == 2 else { fail("Expected one PDF path") }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
      let size = attributes[.size] as? NSNumber, size.intValue <= 52_428_800,
      let pdf = PDFDocument(url: url), !pdf.isLocked, pdf.pageCount > 0, pdf.pageCount <= 500 else {
    fail("PDF unavailable, encrypted or exceeds the 50 MB / 500 page OCR limits")
}
var pages = [String]()
var lowConfidence = [Int]()
var cpuFallback = [Int]()
for index in 0..<pdf.pageCount {
    do {
      try autoreleasepool {
        guard let page = pdf.page(at: index) else { fail("PDF page unavailable") }
        let bounds = page.bounds(for: .mediaBox)
        let factor = min(3.0, 2400.0 / max(bounds.width, bounds.height))
        let thumbnail = page.thumbnail(of: NSSize(width: bounds.width * factor, height: bounds.height * factor), for: .mediaBox)
        guard let image = thumbnail.cgImage(forProposedRect: nil, context: nil, hints: nil) else { fail("Page rendering failed") }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["en-US"]
        request.usesLanguageCorrection = false
        do {
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        } catch {
            // Some macOS compute backends fail on otherwise valid retained PDFs.
            // Retry on CPU without changing text-quality or confidence requirements.
            request.usesCPUOnly = true
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
            cpuFallback.append(index + 1)
        }
        let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first }
        let ocr = lines.map { $0.string }.joined(separator: "\n")
        let native = page.string ?? ""
        // Keep a longer native text layer instead of replacing it with shorter OCR output.
        pages.append(native.count > ocr.count ? native : ocr)
        if ocr.count >= native.count && lines.contains(where: { $0.confidence < 0.80 }) {
            lowConfidence.append(index + 1)
        }
      }
    } catch {
        fail("OCR failed on page \(index + 1), including CPU fallback: \(error)")
    }
}
let result: [String: Any] = ["pages": pages, "pages_expected": pdf.pageCount, "low_confidence_pages": lowConfidence, "cpu_fallback_pages": cpuFallback]
let data = try JSONSerialization.data(withJSONObject: result)
FileHandle.standardOutput.write(data)
