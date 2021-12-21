package xyz.jpon.ka.processing;

import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.geom.AffineTransform;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;

public class DetectColumns {
	protected final Mask mask;

	public DetectColumns(File inDir) throws IOException {
		final File maskFile = new File(inDir, "ocr/column-mask.png");
		this.mask = Mask.createMask(maskFile, .94);
	}

	/**
	 * カラムに分割する。
	 * 
	 * @param b
	 * @return
	 */
	public Rectangle[] detectColumns(BufferedImage orgim, int count, int columnWidth) {
		int[] image;
		int w = orgim.getWidth(null);
		int h = orgim.getHeight(null);
		{
			BufferedImage binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) binim.getGraphics();
			g2d.drawImage(orgim, 0, 0, w, h, null);
			image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);
		}

		final BufferedImage workImage = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
		Graphics2D wg = (Graphics2D) workImage.getGraphics();
		Rectangle[] columnRects = new Rectangle[count];
		int ystart = 0;
		int yend = h - this.mask.h - 1;
		int xx = 0, hh = 0;
		for (int i = 0; i < count + 1; ++i) {
			int xstart = i == 0 ? 0 : columnRects[i - 1].x + columnWidth;
			OUTER: for (int y = ystart; y < h - this.mask.h; ++y) {
				for (int x = xstart; x < xstart + columnWidth && x < w - this.mask.w; ++x) {
					if (this.mask.match(image, x, y, w)) {
						// 上端検出
						x += this.mask.w / 2;
						if (i > 0) {
							Rectangle column = columnRects[i - 1];
							column.width = x - column.x;
							if (y < column.y) {
								column.height += column.y - y;
								column.y = y;
							}
						}
						if (i < count) {
							columnRects[i] = new Rectangle(x, y, 0, 0);
							ystart = y - this.mask.h;
						}
						break OUTER;
					}
				}
			}
			if (i < count && columnRects[i] == null) {
				throw new IllegalStateException("column:" + i);
			}
			OUTER: for (int y = yend; y >= 0; --y) {
				for (int x = xstart; x < xstart + columnWidth && x < w - this.mask.w; ++x) {
					if (this.mask.match(image, x, y, w)) {
						// 下端検出
						x += this.mask.w / 2;
						if (i > 0) {
							// 傾き補正
							Rectangle column = columnRects[i - 1];
							if (y > column.y + column.height) {
								column.height += y - (column.y + column.height);
							}
							System.out.println(xx + "/" + column.x);
							double theta = Math.atan2(xx - column.x, hh);
							BufferedImage im = orgim.getSubimage(column.x, column.y, column.width, column.height);
							wg.setTransform(AffineTransform.getRotateInstance(theta));
							wg.drawImage(im, column.x, column.y, null);
							int s = (int)(Math.sin(theta) * column.width);
							System.out.println(s);
							column.y -= s;
							column.height += s * 2;
						}
						if (i < count) {
							Rectangle column = columnRects[i];
							column.height = y - column.y + this.mask.h;
							yend = y + this.mask.h * 2;
							xx = x;
							hh = column.height;
						}
						break OUTER;
					}
				}
			}
			if (i < count && columnRects[i].height == 0) {
				throw new IllegalStateException();
			}
			System.out.println(i);
		}

		Graphics2D g2d = (Graphics2D) orgim.getGraphics();
		g2d.drawImage(workImage, 0, 0, null);
		workImage.flush();

		return columnRects;
	}
}
