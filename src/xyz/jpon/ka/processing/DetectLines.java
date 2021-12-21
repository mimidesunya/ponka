package xyz.jpon.ka.processing;

import java.awt.Rectangle;
import java.util.List;

public class DetectLines {
	private DetectLines() {
		// ignore
	}

	public static void detectLines(int[] image, int iw, int x, int y, int width, int height, List<Rectangle> lines) {
		int preCount = 0;
		int ry = 0;
		int yy = 0;
		double dw = width;
		for (; yy < height; ++yy) {
			int count = 0;
			for (int xx = 0; xx < width; ++xx) {
				if (image[(y + yy) * iw + (x + xx)] == 0) {
					++count;
				}
			}
			if (count < preCount && count / dw < 0.01) {
				if (yy - ry > 30) {
					lines.add(new Rectangle(x, ry + y, width, yy - ry));
				}
				ry = yy;
			}
			else if (count > preCount && preCount / dw < 0.01) {
				ry = yy - 1;
			}
			preCount = count;
		}
		if (yy - ry > 30) {
			lines.add(new Rectangle(x, ry + y, width, yy - ry));
		}
	}
}
