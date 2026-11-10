import AppKit
import Foundation

let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
for (name, pixels) in [("icon_16x16", 16), ("icon_16x16@2x", 32), ("icon_32x32", 32),
                       ("icon_32x32@2x", 64), ("icon_128x128", 128), ("icon_128x128@2x", 256),
                       ("icon_256x256", 256), ("icon_256x256@2x", 512),
                       ("icon_512x512", 512), ("icon_512x512@2x", 1024)] {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.cgContext.scaleBy(x: CGFloat(pixels)/1024, y: CGFloat(pixels)/1024)
    NSColor(calibratedRed: 0.08, green: 0.14, blue: 0.25, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 80, y: 80, width: 864, height: 864), xRadius: 184, yRadius: 184).fill()
    NSColor(calibratedRed: 0.68, green: 0.77, blue: 0.90, alpha: 0.5).setStroke()
    let grid = NSBezierPath()
    grid.lineWidth = 9
    for i in 0..<5 {
        let coordinate = CGFloat(248 + 132*i)
        grid.move(to: NSPoint(x: coordinate, y: 248)); grid.line(to: NSPoint(x: coordinate, y: 776))
        grid.move(to: NSPoint(x: 248, y: coordinate)); grid.line(to: NSPoint(x: 776, y: coordinate))
    }
    grid.stroke()
    NSColor(calibratedRed: 0.96, green: 0.88, blue: 0.74, alpha: 1).setFill()
    let circle = NSBezierPath(ovalIn: NSRect(x: 284, y: 284, width: 456, height: 456))
    circle.fill()
    NSColor(calibratedRed: 0.70, green: 0.17, blue: 0.15, alpha: 1).setStroke()
    circle.lineWidth = 14; circle.stroke()
    let inner = NSBezierPath(ovalIn: NSRect(x: 307, y: 307, width: 410, height: 410))
    inner.lineWidth = 5; inner.stroke()
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    ("帅" as NSString).draw(in: NSRect(x: 304, y: 345, width: 416, height: 370), withAttributes: [
        .font: NSFont(name: "Songti SC", size: 300) ?? NSFont.systemFont(ofSize: 280),
        .foregroundColor: NSColor(calibratedRed: 0.70, green: 0.17, blue: 0.15, alpha: 1),
        .paragraphStyle: paragraph
    ])
    NSGraphicsContext.restoreGraphicsState()
    let data = bitmap.representation(using: .png, properties: [:])!
    try data.write(to: directory.appendingPathComponent(name + ".png"))
}
