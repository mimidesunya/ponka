package xyz.jpon.ka.processing;

import java.awt.Rectangle;
import java.util.ArrayList;
import java.util.List;

import xyz.jpon.ka.image.BinaryImage;
import xyz.jpon.ka.image.BinaryImage.FloodResult;

public class SegmentationUtils {
	private SegmentationUtils() {
		// ignore
	}

	static final int COLUMN_COUNT = 4;

	/**
	 * カラムに分割する。
	 * 
	 * @param b
	 * @return
	 */
	public static Rectangle[] detectColumns(BinaryImage b) {
		final int w = b.getWidth();
		final int h = b.getHeight();

		// カラム境界線を認識
		Rectangle[] columnRects = new Rectangle[COLUMN_COUNT];
		{
			int state = 0;
			int column = 0;
			Rectangle rect = null;
			LOOP: for (int x = (int) (w * .01); x < w; ++x) {
				int maxRun = b.getVertMaxRun(x, 0, h, true, 2);
				switch (state) {
				case 0:
					if (maxRun / (double) h >= .1) {
						if (rect != null) {
							int cw = x - rect.x;
							if (cw < 1000 || cw > 1100) {
								throw new IllegalStateException("cw="+cw);
							}
							rect.width = cw;
							// カラムの上下枠認識
							int state2 = 0;
							LOOP2: for (int y = 300; y < h; ++y) {
								// カラム上部の線を検出
								int maxRun2 = b.getHrizMaxRun(rect.x, y, rect.width, true, 2);
								switch (state2) {
								case 0:
									if (maxRun2 / (float) rect.width > .1) {
										state2 = 1;
									}
									break;
								case 1:
									if (maxRun2 / (float) rect.width < .01) {
										rect.y = y;
										break LOOP2;
									}
								}
							}
							for (int y = rect.y+6200; y < h; ++y) {
								// 余白部分に線がある場所を検出
								int count = b.getHrizCount(rect.x, y, 30, true);
								if (count / (float) 30 > .9) {
									rect.height = y - rect.y - 1;
									break;
								}
							}
							columnRects[column] = rect;
							if (++column > columnRects.length) {
								break LOOP;
							}
						}
						rect = new Rectangle();
						state = 1;
					}
					break;
				case 1:
					if (maxRun / (double) h < .05) {
						rect.x = x;
						state = 0;
					}
				}
			}
			if (column < columnRects.length) {
				throw new IllegalStateException();
			}
		}
		return columnRects;
	}

	static final int HEIGHT_THRESHOLD = 25;

	public static Rectangle[] detectEntries(BinaryImage b, Rectangle c) {
		// 行を分割
		Rectangle tc = new Rectangle(c);
		xTrim(b, tc);
		final double LINE_THRESHOLD = .1;
		List<Rectangle> rows = new ArrayList<Rectangle>();
		Rectangle row = new Rectangle();
		row.y = c.y;
		row.x = c.x;
		row.width = c.width;
		{
			int state = 0, ady = 0, run = 0;
			for (int y = 0; y < tc.height; ++y) {
				int hmaxRun = b.getHrizMaxRun(tc.x, tc.y + y, tc.width, true, 2);
				int hcount = b.getHrizCount(tc.x, tc.y + y, tc.width, true);
				switch (state) {
				case 0:
					if (hmaxRun / (double) tc.width > LINE_THRESHOLD) {
						// 広告枠検出
						ady = y + c.y;
						state = 2;
						run = 0;
					} else if (hcount >= 8) {
						if (++run >= 3) {
							state = 1;
							y -= run;
							run = 0;
						}
					} else {
						row.y = y + c.y;
						run = 0;
					}
					break;

				case 1:
					int height = y + c.y - row.y;
					if (height > HEIGHT_THRESHOLD && hcount < 8) {
						row.height = height;
						rows.add(row);
						row = new Rectangle();
						row.y = y + c.y;
						row.x = c.x;
						row.width = c.width;
						state = 0;
					} else if (hmaxRun / (double) tc.width > LINE_THRESHOLD) {
						// 広告枠検出
						ady = y + c.y;
						state = 2;
					}
					break;

				case 2:
					if (hmaxRun / (double) tc.width < LINE_THRESHOLD) {
						state = 3;
					}
					break;

				case 3:
					if (hmaxRun / (double) tc.width > LINE_THRESHOLD) {
						state = 4;
					}
					break;

				case 4:
					if (hmaxRun / (double) tc.width < .01) {
						b.fill(new Rectangle(c.x, ady, tc.width, y + c.y - ady), false);
						row.y = y + c.y;
						state = 0;
					}
					break;
				}
			}
		}
		int height = c.height + c.y - row.y;
		if (height > HEIGHT_THRESHOLD) {
			row.height = height;
			rows.add(row);
		}

		// 点線を除去
		final int FLOOD_MAX = 100;
		for (Rectangle r : rows) {
			Rectangle preDotRun = null;
			int preDots = 0;
			for (int y = 0; y < r.height; ++y) {
				Rectangle dotRun = null;
				int dots = 0;
				Rectangle maxDotRun = null;
				int maxDots = 0;
				for (int x = 0; x < r.width / 2; ++x) {
					FloodResult f = b.flood(x + r.x, y + r.y, FLOOD_MAX);
					if (f != null) {
						// 点線の縦横幅は8px,面積は48程度
						if (f.bounds.width <= 15 && f.bounds.height <= 15 && f.area <= 70) { // 点線と判定
							++dots;
							if (dotRun == null) {
								dotRun = f.bounds;
							} else {
								dotRun.add(f.bounds);
							}
							if (dots >= 3 && dots > maxDots) {
								maxDotRun = dotRun;
								maxDots = dots;
							}
						} else {
							dots = 0;
							dotRun = null;
						}
						x = f.bounds.x + f.bounds.width - r.x;
					}
				}
				if (maxDots < preDots) {
					preDotRun.width += 1;
					preDotRun.height += 1;
					b.fill(preDotRun, false);
					preDots = 0;
					preDotRun = null;
				} else if (maxDots >= 3) {
					preDots = maxDots;
					preDotRun = maxDotRun;
				}

			}
		}

		// 大かっこを除去
		{
			List<Rectangle> fills = new ArrayList<Rectangle>();
			for (Rectangle r : rows) {
				if (r.height < HEIGHT_THRESHOLD * 3) {
					continue;
				}
				int y = r.y + r.height / 2;
				for (int x = 0; x < r.width; ++x) {
					FloodResult f = b.flood(x + r.x, y, FLOOD_MAX);
					if (f != null) {
						if (f.bounds.height > HEIGHT_THRESHOLD * 3) {
							fills.add(new Rectangle(f.bounds.x, r.y, f.bounds.width, r.height));
						}
						x = f.bounds.x + f.bounds.width - r.x;
					}
				}
			}
			for (Rectangle r : fills) {
				b.fill(r, false);
			}
			b.apply();
		}

		return rows.toArray(new Rectangle[rows.size()]);
	}

	public static void xTrim(BinaryImage b, Rectangle r) {
		int sx = 0, ex = r.width + r.x;
		{
			int run = 0;
			for (int x = 0; x < r.width; ++x) {
				if (b.getVertCount(r.x + x, r.y, r.height, true) >= 3) {
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
				if (b.getVertCount(r.x + x, r.y, r.height, true) >= 3) {
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

	public static Rectangle[] detectLines(BinaryImage b, Rectangle r) {
		List<Rectangle> lines = new ArrayList<Rectangle>();

		if (r.height < HEIGHT_THRESHOLD * 3) {
			lines.add(r);
		} else {
			Rectangle rr = null;
			int run = 0;
			for (int y = 0; y < r.height; ++y) {
				int maxRun = b.getHrizMaxRunForLine(r.x, r.y + y, r.width);
				if (maxRun / (double) r.width <= 0.8) {
					++run;
					if (rr == null && run >= 3) {
						rr = new Rectangle();
						rr.x = r.x;
						rr.y = y + r.y - run;
						rr.width = r.width;
					}
				} else {
					run = 0;
					if (rr != null) {
						rr.height = y + r.y - rr.y;
						if (rr.height > HEIGHT_THRESHOLD) {
							lines.add(rr);
							rr = null;
						}
					}
				}
			}
			if (rr != null) {
				rr.height = r.height + r.y - rr.y;
				if (rr.height > HEIGHT_THRESHOLD) {
					lines.add(rr);
				}
			}
			if (lines.isEmpty()) {
				lines.add(r);
			}
		}
		for (Rectangle rr : lines) {
			xTrim(b, rr);
		}

		return (Rectangle[]) lines.toArray(new Rectangle[lines.size()]);
	}

	public static Entry analyzeEntry(BinaryImage b, Rectangle r) {
		// 各行を解析
		int nameStart = 20;
		int addrEnd = r.width - 20;
		int numberStart = 0;
		{
			LOOP: for (int x = 480; x < r.width; ++x) {
				for (int y = 0; y < r.height; ++y) {
					FloodResult f = b.flood(x + r.x, y + r.y, 100);
					if (f != null && f.bounds.width >= 20 && f.bounds.height >= 33) {
						numberStart = f.bounds.x - r.x;
						break LOOP;
					}
				}
			}
		}
		if (numberStart == 0) {
			return null;
		}

		int numberEnd = numberStart + 214;
		// 番号の後の「代」などを消す。
		b.fill(new Rectangle(r.x + numberEnd, r.y, 36, r.height), false);

		Entry entry = new Entry();
		entry.bounds = r;
		entry.names = SegmentationUtils.detectLines(b,
				new Rectangle(r.x + nameStart, r.y, numberStart - nameStart, r.height));
		entry.nums = SegmentationUtils.detectLines(b,
				new Rectangle(r.x + numberStart, r.y, numberEnd - numberStart, r.height));
		entry.addrs = SegmentationUtils.detectLines(b,
				new Rectangle(r.x + numberEnd, r.y, addrEnd - numberEnd, r.height));
		return entry;
	}
}
