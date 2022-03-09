package xyz.jpon.ka.processing;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.IOException;

public class ErasePatterns {
	protected final Mask[] masks;

	public ErasePatterns(Mask[] masks) throws IOException {
		this.masks = masks;
	}

	/**
	 * パターンを消す。
	 * 
	 * @param b
	 * @return
	 */
	public void erasePatterns(BufferedImage binim, Rectangle column) {
		int[] image;
		int w = binim.getWidth(null);
		int h = binim.getHeight(null);
		image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);
		Graphics2D g2d = (Graphics2D) binim.getGraphics();
		g2d.setColor(Color.WHITE);

		for (int y = 0; y < column.height; ++y) {
			for (int x = 0; x < column.width; ++x) {
				for (Mask mask : this.masks) {
					if (mask.match(image, column.x + x, column.y + y, w)) {
						g2d.fillRect(column.x + x, column.y + y, mask.w, mask.h);
						break;
					}
				}
			}
		}
	}
}
