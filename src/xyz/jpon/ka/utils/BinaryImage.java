package xyz.jpon.ka.utils;

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

	public void shift(Rectangle r, int offset) {
		if (offset < 0) {
			for (int y = 0; y < r.height; ++y) {
				for (int x = 0; x < r.width; ++x) {
					this.set(x + r.x + offset, y + r.y, this.get(x + r.x, y + r.y));
				}
			}
		} else if (offset > 0) {
			for (int y = 0; y < r.height; ++y) {
				for (int x = r.width - 1; x >= 0; --x) {
					this.set(x + r.x + offset, y + r.y, this.get(x + r.x, y + r.y));
				}
			}
		}
	}

	public void xTrim(Rectangle r) {
		int[] xcounts = this.getXCounts(r.x, r.y, r.width, r.height, true);
		int sx = 0, ex = r.width + r.x;
		{
			int run = 0;
			for (int x = 0; x < r.width; ++x) {
				if (xcounts[x] >= 3) {
					++run;
					if (run >= 3) {
						sx = x + r.x - run;
						break;
					}
				} else {
					run = 0;
				}
				if (x == r.width - 1) {
					r.width = 0;
					return;
				}
			}
		}
		{
			int run = 0;
			for (int x = r.width - 1; x >= 0; --x) {
				if (xcounts[x] >= 3) {
					++run;
					if (run >= 3) {
						ex = x + r.x + run;
						break;
					}
				} else {
					run = 0;
				}
			}
		}
		r.x = sx;
		r.width = ex - sx;
	}

	public int[] getXScores(int x, int y, int w, int h, boolean black) {
		int[] xscores = new int[w];
		for (int xx = 0; xx < w; ++xx) {
			int run = 0, max = 0;
			for (int yy = 0; yy < h; ++yy) {
				if (this.get(xx + x, yy + y) ^ black) {
					run = 0;
				} else {
					++run;
					if (run > max) {
						max = run;
					}
				}
			}
			xscores[xx] = max;
		}
		return xscores;
	}

	public int[] getXCounts(int x, int y, int w, int h, boolean black) {
		int[] xcounts = new int[w];
		for (int xx = 0; xx < w; ++xx) {
			int count = 0;
			for (int yy = 0; yy < h; ++yy) {
				if (!this.get(xx + x, yy + y) ^ black) {
					++count;
				}
			}
			xcounts[xx] = count;
		}
		return xcounts;
	}

	public int[] getYScores(int x, int y, int w, int h, boolean black) {
		int[] yscores = new int[h];
		for (int yy = 0; yy < h; ++yy) {
			int run = 0, max = 0;
			for (int xx = 0; xx < w; ++xx) {
				if (this.get(xx + x, yy + y) ^ black) {
					run = 0;
				} else {
					++run;
					if (run > max) {
						max = run;
					}
				}
			}
			yscores[yy] = max;
		}
		return yscores;
	}

	public int[] getYCounts(int x, int y, int w, int h, boolean black) {
		int[] ycounts = new int[h];
		for (int yy = 0; yy < h; ++yy) {
			int count = 0;
			for (int xx = 0; xx < w; ++xx) {
				if (!this.get(xx + x, yy + y) ^ black) {
					++count;
				}
			}
			ycounts[yy] = count;
		}
		return ycounts;
	}

	public void apply() {
		this.binim.setData(this.raster);
	}

	public void cancel() {
		this.raster = this.binim.copyData(this.raster);
	}

	public Rectangle flood(int x, int y, int max) {
		if (!this.get(x, y)) {
			return null;
		}
		BitSet buff = new BitSet(max * max * 4);
		int bx = x - max;
		int by = y - max;
		Rectangle r = new Rectangle();
		r.x = x;
		r.y = y;
		this.flood(x, y, r, max, bx, by, buff);
		return r;
	}

	private void flood(int x, int y, Rectangle r, int max, int bx, int by, BitSet buff) {
		int width = this.getWidth();
		int height = this.getHeight();
		int fillL = x;
		do {
			buff.set((y - by) * max + (fillL - bx));
			r.add(fillL, y);
			fillL--;
		} while (r.width < max && r.height < max && fillL >= 0
				&& (this.get(fillL, y) && !buff.get((y - by) * max + (fillL - bx))));
		fillL++;

		// find the right right side, filling along the way
		int fillR = x;
		do {
			buff.set((y - by) * max + (fillR - bx));
			r.add(fillR, y);
			fillR++;
		} while (r.width < max && r.height < max && fillR < width - 1
				&& (this.get(fillR, y) && !buff.get((y - by) * max + (fillR - bx))));
		fillR--;

		// checks if applicable up or down
		for (int i = fillL; i <= fillR; i++) {
			if (r.width < max && r.height < max && y > 0
					&& (this.get(i, y - 1) && !buff.get(((y - 1) - by) * max + (i - bx))))
				flood(i, y - 1, r, max, bx, by, buff);
			if (r.width < max && r.height < max && y < height - 1
					&& (this.get(i, y + 1) && !buff.get(((y + 1) - by) * max + (i - bx))))
				flood(i, y + 1, r, max, bx, by, buff);
		}
	}
}
