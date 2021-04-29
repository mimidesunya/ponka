package xyz.jpon.ka.utils;

import java.awt.Graphics2D;
import java.awt.geom.AffineTransform;
import java.awt.image.BufferedImage;

public class ImageProcessingUtils {
	private ImageProcessingUtils() {
		// ignore
	}

	/**
	 * ピクセルが墨であるかの判定。
	 * 
	 * @param rgb
	 * @return
	 */
	public static boolean isInk(int rgb) {
		int r = (rgb >> 16) & 0xFF;
		int g = (rgb >> 8) & 0xFF;
		int b = (rgb >> 0) & 0xFF;
		return (r + g + b) / 3 < 0x80;
	}

	/**
	 * 傾き、歪み補正を実行する。
	 * 
	 * @param image
	 * @param right 右ページであればtrue
	 */
	public static void deskew(BufferedImage image, boolean right) {
		final int w = image.getWidth();
		final int h = image.getHeight();
		Graphics2D srcg = (Graphics2D) image.getGraphics();
		final BufferedImage destImage = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
		Graphics2D destg = (Graphics2D) destImage.getGraphics();

		{
			int top = 480, bottom = 4480;
			int start, end, step;
			if (right) {
				start = 100;
				end = 200;
				step = 1;
			} else {
				start = w - 100;
				end = w - 200;
				step = -1;
			}
			int x1 = 0;
			{
				int run = 0;
				for (int x = start; x != end; x += step) {
					if (isInk(image.getRGB(x, top))) {
						++run;
					} else {
						if (run >= 6) {
							x1 = x;
							break;
						}
						run = 0;
					}
				}
			}
			int x2 = 0;
			{
				int run = 0;
				for (int x = start; x != end; x += step) {
					if (isInk(image.getRGB(x, bottom))) {
						++run;
					} else {
						if (run >= 6) {
							x2 = x;
							break;
						}
						run = 0;
					}
				}
			}
			// 傾きの分逆回転
			double theta = Math.atan2(x2 - x1, (bottom - top));
			destg.setTransform(AffineTransform.getRotateInstance(theta));
			destg.drawImage(image, 0, 0, null);
			destg.setTransform(AffineTransform.getRotateInstance(0));
			srcg.drawImage(destImage, 0, 0, null);

			// 重力による歪み補正
			int block = 10;
			for (int y = top; y < h - 30; y += block) {
				int run = 0;
				for (int x = start; x != end; x += step) {
					if (isInk(image.getRGB(x, y + block / 2))) {
						++run;
					} else {
						if (run >= 6) {
							x2 = x;
							break;
						}
						run = 0;
					}
				}
				int shift = x1 - x2;
				if (shift != 0 && shift < 30 && shift > -30) {
					destg.drawImage(image, 60 + shift, y, w - 60 + shift, y + block, 60, y, w - 60, y + block, null);
				}
			}
			srcg.drawImage(destImage, 0, 0, null);
			destImage.flush();
		}
	}
	
	/**
	 * 画像を二値化する。
	 * @param image
	 * @return
	 */
	public static BinaryImage toBinary(BufferedImage image) {
		final int w = image.getWidth();
		final int h = image.getHeight();
		BufferedImage binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
		for (int y = 0; y < h; ++y) {
			for (int x = 0; x < w; ++x) {
				binim.setRGB(x, y, isInk(image.getRGB(x, y)) ? 0 : 0xFFFFFFFF);
			}
		}
		return new BinaryImage(binim);
	}
}