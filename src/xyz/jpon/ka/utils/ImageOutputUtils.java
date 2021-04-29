package xyz.jpon.ka.utils;

import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.text.DecimalFormat;
import java.text.NumberFormat;
import java.util.List;

import javax.imageio.ImageIO;

public class ImageOutputUtils {
	private ImageOutputUtils() {
		// ignore
	}

	static final NumberFormat FORMAT = new DecimalFormat("0000");

	public static void reconstruct(BinaryImage binim, List<Entry> entries, String pageName, File outDir)
			throws IOException {
		File pageDir = new File(outDir, pageName);
		pageDir.mkdirs();
		final int padding = 50, margin = 5;
		int count = 0;
		for (Entry e : entries) {
			int maxh = 0, maxw = 0;
			for (Rectangle r : e.names) {
				if (maxh < r.height) {
					maxh = r.height;
				}
				maxw += r.width + padding;
			}
			for (Rectangle r : e.nums) {
				if (maxh < r.height) {
					maxh = r.height;
				}
				maxw += r.width + padding;
			}
			for (Rectangle r : e.addrs) {
				if (maxh < r.height) {
					maxh = r.height;
				}
				maxw += r.width + padding;
			}

			BufferedImage newim = new BufferedImage(maxw + margin * 2, maxh + margin * 2,
					BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) newim.getGraphics();
			g2d.setColor(Color.WHITE);
			g2d.fillRect(0, 0, newim.getWidth(), newim.getHeight());
			g2d.setColor(Color.BLACK);
			g2d.setFont(new Font("serif", Font.BOLD, (int)(padding*1.2)));

			int y = margin, x = margin;
			for (Rectangle r : e.names) {
				g2d.drawImage(binim.getImage(), x, y, x + r.width, y + r.height, r.x, r.y, (int) r.getMaxX(),
						(int) r.getMaxY(), null);
				x += r.width + padding / 3;
				g2d.drawString("/", x, y+r.height * 95 / 100);
				x += padding * 2 / 3;
			}
			for (Rectangle r : e.nums) {
				g2d.drawImage(binim.getImage(), x, y, x + r.width, y + r.height, r.x, r.y, (int) r.getMaxX(),
						(int) r.getMaxY(), null);
				x += r.width + padding / 3;
				g2d.drawString("/", x, y+r.height * 95 / 100);
				x += padding * 2 / 3;
			}
			for (Rectangle r : e.addrs) {
				g2d.drawImage(binim.getImage(), x, y, x + r.width, y + r.height, r.x, r.y, (int) r.getMaxX(),
						(int) r.getMaxY(), null);
				x += r.width + padding / 3;
				g2d.drawString("/", x, y+r.height * 95 / 100);
				x += padding * 2 / 3;
			}
			File outFile = new File(pageDir, FORMAT.format(++count) + ".png");
			ImageIO.write(newim, "png", outFile);
		}
	}

}
