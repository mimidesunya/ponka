package xyz.jpon.ka.utils;

import java.awt.Rectangle;
import java.util.ArrayList;
import java.util.List;

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

		// ページの上下枠認識
		int[] yscores = b.getYScores(0, 0, w, h, true);
		int vtop = 0, vbottom = 0;
		{
			int state = 0;
			LOOP: for (int y = 50; y < h; ++y) {
				switch (state) {
				case 0:
					if (yscores[y] / (double) w > .2) {
						state = 1;
					}
					break;
				case 1:
					if (yscores[y] / (double) w < .01) {
						vtop = y;
						break LOOP;
					}
				}
			}
		}
		{
			int state = 0;
			LOOP: for (int y = h - 50; y > 0; --y) {
				switch (state) {
				case 0:
					if (yscores[y] / (double) w > .2) {
						state = 1;
					}
					break;
				case 1:
					if (yscores[y] / (double) w < .01) {
						vbottom = y;
						break LOOP;
					}
				}
			}
		}
		final int top = vtop, bottom = vbottom;

		// カラムを認識
		int[] xscores = b.getXScores(0, 0, w, h, true);
		Rectangle[] columnRects = new Rectangle[COLUMN_COUNT];
		{
			int state = 0;
			int column = 0;
			Rectangle rect = null;
			LOOP: for (int x = (int) (w * .01); x < w; ++x) {
				switch (state) {
				case 0:
					if (xscores[x] / (double) h > .2) {
						if (rect != null) {
							rect.width = x - rect.x;
							columnRects[column] = rect;
							if (++column > COLUMN_COUNT) {
								break LOOP;
							}
						}
						rect = new Rectangle();
						rect.y = top;
						rect.height = bottom - top;
						state = 1;
					}
					break;
				case 1:
					if (xscores[x] / (double) h < .1) {
						rect.x = x;
						state = 0;
					}
				}
			}
		}
		return columnRects;
	}

	static final int HEIGHT_THRESHOLD = 25;

	public static Rectangle[] detectEntries(BinaryImage b, Rectangle c) {
		// 行を分割
		Rectangle tc = new Rectangle(c);
		b.xTrim(tc);
		int[] yscores = b.getYScores(tc.x, tc.y, tc.width, tc.height, true);
		int[] ycounts = b.getYCounts(tc.x, tc.y, tc.width, tc.height, true);
		final double LINE_THRESHOLD = .2;
		List<Rectangle> rows = new ArrayList<Rectangle>();
		Rectangle row = new Rectangle();
		row.y = c.y;
		row.x = c.x;
		row.width = c.width;
		{
			int state = 0, ady = 0, run = 0;
			for (int y = 0; y < tc.height; ++y) {
				switch (state) {
				case 0:
					if (yscores[y] / (double) tc.width > LINE_THRESHOLD) {
						// 広告枠検出
						ady = y + c.y;
						state = 2;
						run = 0;
					} else if (ycounts[y] >= 8) {
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
					if (height > HEIGHT_THRESHOLD && ycounts[y] < 8) {
						row.height = height;
						rows.add(row);
						row = new Rectangle();
						row.y = y + c.y;
						row.x = c.x;
						row.width = c.width;
						state = 0;
					} else if (yscores[y] / (double) tc.width > LINE_THRESHOLD) {
						// 広告枠検出
						ady = y + c.y;
						state = 2;
					}
					break;

				case 2:
					if (yscores[y] / (double) tc.width < LINE_THRESHOLD) {
						state = 3;
					}
					break;

				case 3:
					if (yscores[y] / (double) tc.width > LINE_THRESHOLD) {
						state = 4;
					}
					break;

				case 4:
					if (yscores[y] / (double) tc.width < .01) {
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

		final int FLOOD_MAX = 100;
		final int DOT_THRESHOLD = 20;
		// 点線を除去
		for (Rectangle r : rows) {
			Rectangle preDotRun = null;
			int preDots = 0;
			for (int y = 0; y < r.height; ++y) {
				Rectangle dotRun = null;
				int dots = 0;
				Rectangle maxDotRun = null;
				int maxDots = 0;
				for (int x = 0; x < r.width / 2; ++x) {
					Rectangle f = b.flood(x + r.x, y + r.y, FLOOD_MAX);
					if (f != null) {
						int size = f.width + f.height;
						if (size <= DOT_THRESHOLD) { // 点線と判定
							++dots;
							if (dotRun == null) {
								dotRun = f;
							} else {
								dotRun.add(f);
							}
							if (dots >= 3 && dots > maxDots) {
								maxDotRun = dotRun;
								maxDots = dots;
							}
						} else {
							dots = 0;
							dotRun = null;
						}
						x = f.x + f.width - r.x;
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
					Rectangle f = b.flood(x + r.x, y, FLOOD_MAX);
					if (f != null) {
						if (f.height > HEIGHT_THRESHOLD * 3) {
							fills.add(new Rectangle(f.x, r.y, f.width, r.height));
						}
						x = f.x + f.width - r.x;
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

	public static Rectangle[] detectLines(BinaryImage b, Rectangle r) {
		List<Rectangle> lines = new ArrayList<Rectangle>();

		if (r.height < HEIGHT_THRESHOLD * 3) {
			lines.add(r);
		} else {
			int[] ywscores = b.getYScores(r.x, r.y, r.width, r.height, false);
			Rectangle rr = null;
			int run = 0;
			for (int y = 0; y < r.height; ++y) {
				if (ywscores[y] / (double) r.width <= 0.8) {
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
			b.xTrim(rr);
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
					Rectangle f = b.flood(x + r.x, y + r.y, 100);
					if (f != null && f.width >= 20 && f.height >= 33) {
						numberStart = f.x - r.x;
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
		entry.names = SegmentationUtils.detectLines(b, new Rectangle(r.x + nameStart, r.y, numberStart - nameStart, r.height));
		entry.nums = SegmentationUtils.detectLines(b, new Rectangle(r.x + numberStart, r.y, numberEnd - numberStart, r.height));
		entry.addrs = SegmentationUtils.detectLines(b, new Rectangle(r.x + numberEnd, r.y, addrEnd - numberEnd, r.height));
		return entry;
	}
}
