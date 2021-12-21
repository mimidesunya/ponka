package xyz.jpon.ka.processing;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;

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
	public void eraseAds(BufferedImage orgim, Rectangle column) {
		int[] image;
		int w = orgim.getWidth(null);
		int h = orgim.getHeight(null);
		{
			BufferedImage binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) binim.getGraphics();
			g2d.drawImage(orgim, 0, 0, w, h, null);
			image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);
		}
		Graphics2D g2d = (Graphics2D) orgim.getGraphics();
		Color fill = new Color(0xFF, 0xCC, 0xCC);
		g2d.setColor(fill);

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
						g2d.fillRect(column.x, column.y + ystart, column.width, y - ystart);
						ystart = 0;
					}
				}
			}
		}
	}
}
