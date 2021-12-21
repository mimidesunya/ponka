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

	public Entry analyzeEntry(BufferedImage orgim, Rectangle entry) {
		int[] image;
		int w = orgim.getWidth(null);
		int h = orgim.getHeight(null);
		{
			BufferedImage binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) binim.getGraphics();
			g2d.drawImage(orgim, 0, 0, w, h, null);
			image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);
		}

		List<Rectangle> nums = new ArrayList<Rectangle>();
		int xstart = 480;
		int xend = entry.width - 430;
		int xmin = xend;
		int xmax = 0;
		for (int y = 0; y < entry.height; ++y) {
			for (int x = xstart; x < xend; ++x) {
				if (this.hyphen.match(image, entry.x + x, entry.y + y, w)) {
					int xx = x - 76;
					int ww = 76 + this.hyphen.w + 118;
					nums.add(new Rectangle(entry.x + xx, entry.y + y, ww, this.hyphen.h));
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
		if (nums.isEmpty()) {
			return null;
		}

		List<Rectangle> names = new ArrayList<Rectangle>();
		DetectLines.detectLines(image, w, entry.x + 20, entry.y, xmin - 20, entry.height, names);

		List<Rectangle> addrs = new ArrayList<Rectangle>();
		DetectLines.detectLines(image, w, entry.x + xmax + 30, entry.y, entry.width - xmax - 50 , entry.height, addrs);

		Entry e = new Entry();
		e.bounds = entry;
		e.nums = nums.toArray(new Rectangle[nums.size()]);
		e.names = names.toArray(new Rectangle[names.size()]);
		e.addrs = addrs.toArray(new Rectangle[addrs.size()]);
		return e;
	}
}
