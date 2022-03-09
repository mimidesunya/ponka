package xyz.jpon.ka.processing;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

public class EraseAds {
	protected final Mask mask1, mask2;

	public EraseAds(File inDir) throws IOException {
		{
			final File maskFile = new File(inDir, "ocr/ad1.png");
			this.mask1 = Mask.createMask(maskFile, .90);
		}
		{
			final File maskFile = new File(inDir, "ocr/ad2.png");
			this.mask2 = Mask.createMask(maskFile, .90);
		}
	}

	/**
	 * 広告を消す。
	 * 
	 * @param b
	 * @return
	 */
	public Rectangle[] eraseAds(BufferedImage binim, Rectangle column) {
		int[] image;
		int w = binim.getWidth(null);
		int h = binim.getHeight(null);
		image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);
		Graphics2D g2d = (Graphics2D) binim.getGraphics();
		g2d.setColor(Color.WHITE);

		List<Rectangle> ads = new ArrayList<Rectangle>();
		int ystart = 0;
		int xend = column.width / 6;
		for (int y = 0; y < column.height; ++y) {
			for (int x = 0; x < xend; ++x) {
				if (ystart == 0) {
					if (this.mask1.match(image, column.x + x, column.y + y, w)) {
						ystart = y;
						xend = x + this.mask1.w;
					}
				} else {
					if (this.mask2.match(image, column.x + x, column.y + y, w)) {
						y += this.mask2.h;
						Rectangle ad = new Rectangle(column.x, column.y + ystart, column.width, y - ystart);
						g2d.fill(ad);
						ads.add(ad);
						ystart = 0;
					}
				}
			}
		}
		return ads.toArray(new Rectangle[ads.size()]);
	}
}
