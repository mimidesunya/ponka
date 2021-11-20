package xyz.jpon.ka.image;

import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.awt.image.WritableRaster;
import java.util.BitSet;

/**
 * 二値化された画像を処理するためのクラスです。
 */
public class BinaryImage {
	private final BufferedImage binim;
	private WritableRaster raster;

	/**
	 * 画像を二値化する。
	 * 
	 * @param image
	 * @return
	 */
	public static BinaryImage toBinary(BufferedImage image, Binarizer binr) {
		final int w = image.getWidth();
		final int h = image.getHeight();
		BufferedImage binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
		for (int y = 0; y < h; ++y) {
			for (int x = 0; x < w; ++x) {
				binim.setRGB(x, y, binr.isInk(image.getRGB(x, y)) ? 0xFF000000 : 0xFFFFFFFF);
			}
		}
		return new BinaryImage(binim);
	}

	public BinaryImage(BufferedImage binim) {
		this.binim = binim;
		this.raster = (WritableRaster) binim.getData();
	}

	public BufferedImage getImage() {
		return this.binim;
	}

	public int getWidth() {
		return this.raster.getWidth();
	}

	public int getHeight() {
		return this.raster.getHeight();
	}

	public boolean get(int x, int y) {
		int bit = this.raster.getSample(x, y, 0);
		return bit != 1;
	}

	public void set(int x, int y, boolean bit) {
		this.raster.setSample(x, y, 0, bit ? 0 : 1);
	}

	public void fill(Rectangle r, boolean bit) {
		for (int y = 0; y < r.height; ++y) {
			for (int x = 0; x < r.width; ++x) {
				this.set(x + r.x, y + r.y, bit);
			}
		}
	}

	public int getHrizMaxRun(int x, int y, int w, boolean black, int maxGap) {
		int run = 0, max = 0, gap = 0;
		for (int xx = 0; xx < w; ++xx) {
			if (this.get(xx + x, y) ^ black) {
				if (++gap > maxGap) {
					run = 0;
					continue;
				}
			} else {
				gap = 0;
			}
			++run;
			if (run > max) {
				max = run;
			}
		}
		return max;
	}

	public int getHrizMaxRunForLine(int x, int y, int w) {
		int run = 0, max = 0;
		for (int xx = 0; xx < w; ++xx) {
			if (this.get(xx + x, y) && (y == 0 || this.get(xx + x, y - 1))) {
				run = 0;
				continue;
			}
			++run;
			if (run > max) {
				max = run;
			}
		}
		return max;
	}

	/**
	 * 指定した地点から縦方向のhピクセルの最大のランを計測します。
	 * 
	 * @param x
	 * @param y
	 * @param h
	 * @param black
	 * @param maxGap 許容する最大ギャップサイズ。
	 * @return
	 */
	public int getVertMaxRun(int x, int y, int h, boolean black, int maxGap) {
		int run = 0, max = 0, gap = 0;
		for (int yy = 0; yy < h; ++yy) {
			if (this.get(x, yy + y) ^ black) {
				if (++gap > maxGap) {
					run = 0;
					continue;
				}
			} else {
				gap = 0;
			}
			++run;
			if (run > max) {
				max = run;
			}
		}
		return max;
	}

	public int getHrizCount(int x, int y, int w, boolean black) {
		int count = 0;
		for (int xx = 0; xx < w; ++xx) {
			if (!this.get(xx + x, y) ^ black) {
				++count;
			}
		}
		return count;
	}

	public int getVertCount(int x, int y, int h, boolean black) {
		int count = 0;
		for (int yy = 0; yy < h; ++yy) {
			if (!this.get(x, yy + y) ^ black) {
				++count;
			}
		}
		return count;
	}

	public void apply() {
		this.binim.setData(this.raster);
	}

	public void cancel() {
		this.raster = this.binim.copyData(this.raster);
	}

	public class FloodResult {
		public int area = 0;
		public Rectangle bounds = new Rectangle();
	}

	public FloodResult flood(int x, int y, int max) {
		if (!this.get(x, y)) {
			return null;
		}
		BitSet buff = new BitSet(max * max * 4);
		int bx = x - max;
		int by = y - max;
		FloodResult r = new FloodResult();
		r.bounds.x = x;
		r.bounds.y = y;
		this.flood(x, y, r, max, bx, by, buff);
		return r;
	}

	private void flood(int x, int y, FloodResult r, int max, int bx, int by, BitSet buff) {
		int width = this.getWidth();
		int height = this.getHeight();
		int fillL = x;
		do {
			buff.set((y - by) * max + (fillL - bx));
			r.area++;
			r.bounds.add(fillL, y);
			fillL--;
		} while (r.bounds.width < max && r.bounds.height < max && fillL >= 0
				&& (this.get(fillL, y) && !buff.get((y - by) * max + (fillL - bx))));
		fillL++;

		// find the right right side, filling along the way
		int fillR = x;
		do {
			buff.set((y - by) * max + (fillR - bx));
			r.area++;
			r.bounds.add(fillR, y);
			fillR++;
		} while (r.bounds.width < max && r.bounds.height < max && fillR < width - 1
				&& (this.get(fillR, y) && !buff.get((y - by) * max + (fillR - bx))));
		fillR--;

		// checks if applicable up or down
		for (int i = fillL; i <= fillR; i++) {
			if (r.bounds.width < max && r.bounds.height < max && y > 0
					&& (this.get(i, y - 1) && !buff.get(((y - 1) - by) * max + (i - bx))))
				flood(i, y - 1, r, max, bx, by, buff);
			if (r.bounds.width < max && r.bounds.height < max && y < height - 1
					&& (this.get(i, y + 1) && !buff.get(((y + 1) - by) * max + (i - bx))))
				flood(i, y + 1, r, max, bx, by, buff);
		}
	}
}
