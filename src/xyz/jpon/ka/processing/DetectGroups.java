package xyz.jpon.ka.processing;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Rectangle;
import java.awt.geom.AffineTransform;
import java.awt.image.AffineTransformOp;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;

import javax.imageio.ImageIO;

public class DetectGroups {
	protected final Mask curl, curl2, top, top2, bottom;

	public DetectGroups(File inDir, boolean left) throws IOException {
		{
			final Image image = ImageIO.read(new File(inDir, "ocr/curl.png"));
			int w = image.getWidth(null);
			int h = image.getHeight(null);
			BufferedImage bim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) bim.getGraphics();
			g2d.drawImage(image, 0, 0, null);

			{
				if (left) {
					AffineTransform tx = AffineTransform.getScaleInstance(-1, 1);
					tx.translate(-w, 0);

					AffineTransformOp op = new AffineTransformOp(tx, AffineTransformOp.TYPE_NEAREST_NEIGHBOR);
					bim = op.filter(bim, null);
				}
				this.curl = Mask.createMask(bim, .93);
			}
		}
		{
			final Image image = ImageIO.read(new File(inDir, "ocr/curl2.png"));
			int w = image.getWidth(null);
			int h = image.getHeight(null);
			BufferedImage bim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) bim.getGraphics();
			g2d.drawImage(image, 0, 0, null);

			{
				if (left) {
					AffineTransform tx = AffineTransform.getScaleInstance(-1, 1);
					tx.translate(-w, 0);

					AffineTransformOp op = new AffineTransformOp(tx, AffineTransformOp.TYPE_NEAREST_NEIGHBOR);
					bim = op.filter(bim, null);
				}
				this.curl2 = Mask.createMask(bim, .93);
			}
		}

		{
			double t = .93;
			final Image image = ImageIO.read(new File(inDir, "ocr/curl-edge.png"));
			int w = image.getWidth(null);
			int h = image.getHeight(null);
			BufferedImage bim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) bim.getGraphics();
			g2d.drawImage(image, 0, 0, null);
			if (left) {
				{
				AffineTransform tx = AffineTransform.getScaleInstance(-1, 1);
				tx.translate(-w, 0);
				AffineTransformOp op = new AffineTransformOp(tx, AffineTransformOp.TYPE_NEAREST_NEIGHBOR);
				bim = op.filter(bim, null);
				this.top = Mask.createMask(bim, t);
				}
				{
					AffineTransform tx = AffineTransform.getScaleInstance(1, -1);
					tx.translate(0, -bim.getHeight(null));
					AffineTransformOp op = new AffineTransformOp(tx, AffineTransformOp.TYPE_NEAREST_NEIGHBOR);
					bim = op.filter(bim, null);
					this.bottom = Mask.createMask(bim, t);
				}
			} else {
				this.top = Mask.createMask(bim, t);
				{
					AffineTransform tx = AffineTransform.getScaleInstance(1, -1);
					tx.translate(0, -bim.getHeight(null));
					AffineTransformOp op = new AffineTransformOp(tx, AffineTransformOp.TYPE_NEAREST_NEIGHBOR);
					bim = op.filter(bim, null);
					this.bottom = Mask.createMask(bim, t);
				}
			}
		}

		{
			double t = .92;
			final Image image = ImageIO.read(new File(inDir, "ocr/curl-top2.png"));
			int w = image.getWidth(null);
			int h = image.getHeight(null);
			BufferedImage bim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) bim.getGraphics();
			g2d.drawImage(image, 0, 0, null);
			if (left) {
				AffineTransform tx = AffineTransform.getScaleInstance(-1, 1);
				tx.translate(-w, 0);
				AffineTransformOp op = new AffineTransformOp(tx, AffineTransformOp.TYPE_NEAREST_NEIGHBOR);
				bim = op.filter(bim, null);
				this.top2 = Mask.createMask(bim, t);
			} else {
				this.top2 = Mask.createMask(bim, t);
			}
		}
	}

	/**
	 * くくり記号を認識する。
	 * 
	 * @param b
	 * @return
	 */
	public void detectGroups(BufferedImage orgim, Rectangle column, int marker, int markerWidth) {
		// 最初に小さなパターンでマッチングして
		// &条件で大きなパターンでマッチングすると高速かつ高精度になる
		int[] image;
		int w = orgim.getWidth(null);
		int h = orgim.getHeight(null);
		{
			BufferedImage binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) binim.getGraphics();
			g2d.drawImage(orgim, 0, 0, w, h, null);
			image = binim.getRaster().getSamples(0, 0, w, h, 0, new int[w * h]);
		}
		Graphics2D g2d = (Graphics2D) orgim.getGraphics();

		Color fill = new Color(0xCC, 0xFF, 0xCC);
		int ystart = 0;
		int xstart = 0;
		int xend = column.width;
		for (int y = 0; y < column.height; ++y) {
			for (int x = xstart; x < xend; ++x) {
				if (ystart == 0) {
					if (this.top.match(image, column.x + x, column.y + y, w)) {
						// 2段/3段くくり記号の検出
						Mask curl = null;
						if (this.curl.match(image, column.x + x, column.y + y, w)) {
							curl = this.curl;
						} else if (this.curl2.match(image, column.x + x, column.y + y, w)) {
							curl = this.curl2;
						}
						if (curl != null) {
							g2d.setColor(fill);
							g2d.fillRect(column.x + x, column.y + y, curl.w, curl.h);
							g2d.setColor(Color.BLACK);
							g2d.fillRect(marker, column.y + y + 6, markerWidth, curl.h - 12);
							y += curl.h / 3 * 2;
							break;
						}
						// 4段以上
						if (this.top2.match(image, column.x + x, column.y + y, w)) {
							System.out.println(y);
							ystart = y;
							xstart = x - 2;
							xend = x + 2;
							y += this.top2.h / 2;
							break;
						}
					}
				} else {
					if (this.bottom.match(image, column.x + x, column.y + y, w)) {
						y += this.bottom.h;
						g2d.setColor(fill);
						g2d.fillRect(column.x + x, column.y + ystart, this.bottom.w, y - ystart);
						g2d.setColor(Color.BLACK);
						g2d.fillRect(marker, column.y + ystart + 6, markerWidth, y - ystart - 12);
						ystart = 0;
						xstart = 0;
						y -= this.bottom.h / 3;
						xend = column.width;
					}
				}
			}
		}
	}
}
