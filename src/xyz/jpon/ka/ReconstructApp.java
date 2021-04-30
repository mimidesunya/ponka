package xyz.jpon.ka;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.text.DecimalFormat;
import java.text.NumberFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import javax.imageio.ImageIO;

import xyz.jpon.ka.utils.BinaryImage;
import xyz.jpon.ka.utils.Entry;
import xyz.jpon.ka.utils.ImageOutputUtils;
import xyz.jpon.ka.utils.ImageProcessingUtils;
import xyz.jpon.ka.utils.SegmentationUtils;

public class ReconstructApp {
	static final NumberFormat FORMAT = new DecimalFormat("0000");

	public static void main(String[] args) throws Exception {
		final File inDir = new File(args[0]);
		final File outDir = new File(args[1]);

		for (int i = 1;; ++i) {
			try {
				process(inDir, outDir, i);
			} catch (RuntimeException e) {
				System.out.println("failed");
			}
		}
	}

	public static void process(File inDir, File outDir, int page) throws IOException {
		// 対象ファイル
		final String pageName = FORMAT.format(page);
		final File file = new File(inDir, pageName + ".png");

		System.out.println("処理開始:" + file);
		final BufferedImage orgim;
		final int w, h;
		{
			final Image image = ImageIO.read(file);
			// PreviewUtils.preview(image, "処理前");
			w = image.getWidth(null);
			h = image.getHeight(null);
			orgim = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
			Graphics2D g2d = (Graphics2D) orgim.getGraphics();
			g2d.drawImage(image, 0, 0, null);
		}

		System.out.println("傾き・歪み補正");
		ImageProcessingUtils.deskew(orgim, page % 2 == 1);
		// PreviewUtils.preview(orgim, "補正後");

		System.out.println("二値化");
		BinaryImage binim = ImageProcessingUtils.toBinary(orgim);
		// PreviewUtils.preview(binim.getImage(), "二値化後");

		System.out.println("カラムを解析");
		Rectangle[] columnRects = SegmentationUtils.detectColumns(binim);
		List<Rectangle> rows = new ArrayList<Rectangle>();
		for (int i = 0; i < columnRects.length; ++i) {
			System.out.println("カラム " + i + "/" + columnRects.length);
			rows.addAll(Arrays.asList(SegmentationUtils.detectEntries(binim, columnRects[i])));
		}
		binim.apply();

		System.out.println("エントリを解析");
		List<Entry> entries = new ArrayList<Entry>();
		for (int i = 0; i < rows.size(); ++i) {
			Entry e = SegmentationUtils.analyzeEntry(binim, rows.get(i));
			if (e != null) {
				entries.add(e);
			}
		}

		BufferedImage aim = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
		{
			Graphics2D g2d = (Graphics2D) aim.getGraphics();
			g2d.setColor(Color.WHITE);
			g2d.fillRect(0, 0, aim.getWidth(), aim.getHeight());
			// 変換後画像
			g2d.drawImage(binim.getImage(), 0, 0, null);
			g2d.setStroke(new BasicStroke(5f));

			// 行の枠を表示
			for (Rectangle r : rows) {
				g2d.setColor(Color.GREEN);
				g2d.drawLine(r.x, r.y, r.x + r.width, r.y);
				g2d.setColor(Color.RED);
				g2d.drawLine(r.x, r.y + r.height, r.x + r.width, r.y + r.height);
			}

			for (Entry e : entries) {
				g2d.setColor(Color.PINK);
				for (Rectangle r : e.names) {
					g2d.draw(r);
				}
				g2d.setColor(Color.RED);
				for (Rectangle r : e.nums) {
					g2d.draw(r);
				}
				g2d.setColor(Color.ORANGE);
				for (Rectangle r : e.addrs) {
					g2d.draw(r);
				}
			}
			File outFile = new File(outDir, pageName + ".png");
			ImageIO.write(aim, "png", outFile);
		}
		// PreviewUtils.preview(aim, "解析後");

		// 再構成
		System.out.println("再構成");
		ImageOutputUtils.reconstruct(binim, entries, pageName, outDir);
	}
}
