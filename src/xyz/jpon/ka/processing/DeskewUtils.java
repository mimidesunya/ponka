package xyz.jpon.ka.processing;

import java.awt.Graphics2D;
import java.awt.geom.AffineTransform;
import java.awt.image.BufferedImage;

import xyz.jpon.ka.image.Binarizer;

public class DeskewUtils {
	private DeskewUtils() {
		// ignore
	}

	/**
	 * 傾き、歪み補正を実行する。
	 * 
	 * @param image
	 * @param right 右ページであればtrue
	 */
	public static void deskew(BufferedImage image, Binarizer binr, boolean right) {
		final int w = image.getWidth();
		final int h = image.getHeight();
		Graphics2D srcg = (Graphics2D) image.getGraphics();
		final BufferedImage destImage = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
		Graphics2D destg = (Graphics2D) destImage.getGraphics();

		int borderWidth = 5;
		int top = 800, bottom = 4480;
		int x1, x2;
		int start, end, step, cside;
		if (right) {
			start = 30;
			end = 300;
			cside = w - 30;
			step = 1;
		} else {
			start = w - 30;
			end = w - 300;
			cside = 30;
			step = -1;
		}
		
		// 傾きの分逆回転
		for (;;) {
			x1 = 0; // 内側の基準位置
			{
				int run = 0;
				for (int x = start; x != end; x += step) {
					if ((binr.isInk(image.getRGB(x, top - borderWidth)) && binr.isInk(image.getRGB(x, top + borderWidth)))
							|| (binr.isInk(image.getRGB(x, top + borderWidth * 2 / 2)) && binr.isInk(image.getRGB(x, top + borderWidth * 2 / 2)))
							|| (binr.isInk(image.getRGB(x, top + borderWidth * 2)) && binr.isInk(image.getRGB(x, top + borderWidth * 2)))) {
						++run;
					} else {
						if (run >= borderWidth) {
							x1 = x;
							break;
						}
						run = 0;
					}
				}
			}
			x2 = 0;
			{
				int run = 0;
				for (int x = start; x != end; x += step) {
					if ((binr.isInk(image.getRGB(x, bottom - borderWidth)) && binr.isInk(image.getRGB(x, bottom + borderWidth)))
							|| (binr.isInk(image.getRGB(x, bottom - borderWidth * 2 / 2)) && binr.isInk(image.getRGB(x, bottom + borderWidth * 2 / 2)))
							|| (binr.isInk(image.getRGB(x, bottom - borderWidth * 2)) && binr.isInk(image.getRGB(x, bottom + borderWidth * 2)))) {
						++run;
					} else {
						if (run >= borderWidth) {
							x2 = x;
							break;
						}
						run = 0;
					}
				}
			}
			if (Math.abs(x2 - x1) > 100) {
				if (top > 2000) {
					throw new IllegalStateException("x1=" + x1 + ",x2=" + x2);
				}
				top += borderWidth;
				continue;
			}
			break;
		}
		System.out.println(x1+"/"+x2);
		double theta = Math.atan2(x2 - x1, (bottom - top));
		destg.setTransform(AffineTransform.getRotateInstance(theta));
		destg.drawImage(image, 0, 0, null);
		destg.setTransform(AffineTransform.getRotateInstance(0));
		srcg.drawImage(destImage, 0, 0, null);

		// 重力による歪み補正
		int block = borderWidth * 2;
		int xx1 = 0; // 外側の基準X位置
		{
			int run = 0;
			for (int x = x1 + 4220 * step; x != cside; x += step) {
				if (binr.isInk(image.getRGB(x, top - borderWidth)) && binr.isInk(image.getRGB(x, top + borderWidth))) {
					++run;
				} else {
					if (run >= borderWidth) {
						xx1 = x;
						break;
					}
					run = 0;
				}
			}
		}
		int pshift = 0, psshift = 0;
		for (int y = top; y < h - block; y += block) {
			int run = 0;
			x2 = 0;
			int xx2 = 0;
			for (int x = x1 + 4220 * step; x != cside; x += step) {
				if (binr.isInk(image.getRGB(x, y - borderWidth)) && binr.isInk(image.getRGB(x, y + borderWidth))) {
					++run;
				} else {
					if (run >= borderWidth) {
						xx2 = x;
						break;
					}
					run = 0;
				}
			}
			run = 0;
			for (int x = start; x != end; x += step) {
				if (binr.isInk(image.getRGB(x, y - borderWidth))
						&& binr.isInk(image.getRGB(x, y + borderWidth))) {
					++run;
				} else {
					if (run >= borderWidth) {
						x2 = x;
						break;
					}
					run = 0;
				}
			}
			int shift = x2 - x1; // 内側のずれ
			int sshift = xx2 - xx1; // 外側のずれ
			if (Math.abs(shift - pshift) >= 3) {
				shift = pshift;
			}
			if (Math.abs(sshift - psshift) >= 3) {
				sshift = psshift;
			}
			if (shift != 0 || sshift != 0) {
				destg.drawImage(image, 60 + shift, y, w - 60 + shift - sshift, y + block, 60, y, w - 60, y + block,
						null);
			}
			pshift = shift;
			psshift = sshift;
		}
		srcg.drawImage(destImage, 0, 0, null);
		destImage.flush();
	}
}
