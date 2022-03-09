package xyz.jpon.ka.processing;

import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.util.ArrayList;
import java.util.List;

public class DetectEntries {
	private DetectEntries() {
		// ignore
	}

	public static void detectEntries(BufferedImage binim, Rectangle column, List<Entry> result) {
		int[] image;
		int w = binim.getWidth(null);
		int h = binim.getHeight(null);
		image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);
		List<Rectangle> rs = new ArrayList<Rectangle>();
		DetectLines.detectLines(image, w, column.x + 10, column.y, column.width - 20, column.height, rs);
		for (Rectangle r : rs) {
			Entry e = new Entry();
			e.bounds = r;
			result.add(e);
		}
	}
}
