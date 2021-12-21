package xyz.jpon.ka.processing;

import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.image.BufferedImage;
import java.awt.image.Raster;
import java.io.File;
import java.io.IOException;

import javax.imageio.ImageIO;

/**
 * マスクパターンです。
 */
public class Mask {
	protected final int[] mask;
	public final int w, h;
	protected final double threshold;
	
	public static Mask createMask(File maskFile, double threshold) throws IOException {
		final Image image = ImageIO.read(maskFile);
		int w = image.getWidth(null);
		int h = image.getHeight(null);
		BufferedImage bim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
		Graphics2D g2d = (Graphics2D) bim.getGraphics();
		g2d.drawImage(image, 0, 0, null);
		return createMask(bim, threshold);
	}
	
	public static Mask createMask(BufferedImage image, double threshold) throws IOException {
		int w = image.getWidth(null);
		int h = image.getHeight(null);
		Raster r = image.getRaster();
		return new Mask(r.getSamples(0, 0, w, h, 0, new int[w * h]), w, h, threshold);
	}

	public Mask(int[] mask, int w, int h, double threshold) {
		this.mask = mask;
		this.w = w;
		this.h = h;
		this.threshold = threshold;
	}

	/**
	 * 画像の指定箇所の一致度がしきい値を超えたらtrueを返します。
	 * 
	 * @param image
	 * @param xx
	 * @param yy
	 * @param imw
	 * @return
	 */
	public boolean match(int[] image, int xx, int yy, int imw) {
		int a = 0;
		for (int y = 0; y < this.h; ++y) {
			for (int x = 0; x < this.w; ++x) {
				if (image[xx + x + (yy + y) * imw] == this.mask[y * this.w + x]) {
					++a;
				}
			}
		}
		return a / (double) (this.w * this.h) >= this.threshold;
	}
}
