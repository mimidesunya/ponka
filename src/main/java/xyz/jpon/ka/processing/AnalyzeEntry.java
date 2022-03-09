package xyz.jpon.ka.processing;

import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import javax.imageio.ImageIO;

import xyz.jpon.ka.processing.Line.Type;

public class AnalyzeEntry {
	protected final Mask hyphen;

	public AnalyzeEntry(File inDir) throws IOException {
		final Image image = ImageIO.read(new File(inDir, "ocr/hyphen.png"));
		int w = image.getWidth(null);
		int h = image.getHeight(null);
		BufferedImage bim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
		Graphics2D g2d = (Graphics2D) bim.getGraphics();
		g2d.drawImage(image, 0, 0, null);
		this.hyphen = Mask.createMask(bim, .95);
	}

	public Entry analyzeEntry(BufferedImage binim, Entry entry) {
		int[] image;
		int w = binim.getWidth(null);
		int h = binim.getHeight(null);
		image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);

		List<Line> lines = new ArrayList<Line>();
		int xstart = 480;
		int xend = entry.bounds.width - 430;
		int xmin = xend;
		int xmax = 0;
		for (int y = 0; y < entry.bounds.height; ++y) {
			for (int x = xstart; x < xend; ++x) {
				if (this.hyphen.match(image, entry.bounds.x + x, entry.bounds.y + y, w)) {
					int xx = x - 76;
					int ww = 76 + this.hyphen.w + 118;
					Line l = new Line(Type.NUMBER);
					l.bounds = new Rectangle(entry.bounds.x + xx, entry.bounds.y + y, ww, this.hyphen.h);
					lines.add(l);
					y += this.hyphen.h;
					if (xmin > xx) {
						xmin = xx;
					}
					ww += xx;
					if (xmax < ww) {
						xmax = ww;
					}
				}
			}
		}
		if (lines.isEmpty()) {
			return null;
		}

		DetectLines.detectLines(image, w, entry.bounds.x + 20, entry.bounds.y, xmin - 20, entry.bounds.height,
				Type.NAME, lines);
		DetectLines.detectLines(image, w, entry.bounds.x + xmax + 30, entry.bounds.y, entry.bounds.width - xmax - 50,
				entry.bounds.height, Type.ADDRESS, lines);

		entry.lines = lines.toArray(new Line[lines.size()]);
		return entry;
	}
}
