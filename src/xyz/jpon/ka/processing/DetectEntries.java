package xyz.jpon.ka.processing;

import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.util.List;

public class DetectEntries {
	private DetectEntries() {
		// ignore
	}

	public static void detectEntries(BufferedImage orgim, Rectangle column, List<Rectangle> result) {
		int[] image;
		int w = orgim.getWidth(null);
		int h = orgim.getHeight(null);
		{
			BufferedImage binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) binim.getGraphics();
			g2d.drawImage(orgim, 0, 0, w, h, null);
			image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);
		}
		DetectLines.detectLines(image, w, column.x + 10, column.y, column.width - 20, column.height,
				result);
	}
}
