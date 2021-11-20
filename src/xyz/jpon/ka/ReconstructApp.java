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

import net.sourceforge.tess4j.ITesseract;
import net.sourceforge.tess4j.Tesseract;
import xyz.jpon.ka.image.Binarizer;
import xyz.jpon.ka.image.BinaryImage;
import xyz.jpon.ka.image.ImageOutputUtils;
import xyz.jpon.ka.image.PreviewUtils;
import xyz.jpon.ka.image.ThreasholdBinarizer;
import xyz.jpon.ka.processing.DeskewUtils;
import xyz.jpon.ka.processing.Entry;
import xyz.jpon.ka.processing.SegmentationUtils;

public class ReconstructApp {
	static final NumberFormat FORMAT = new DecimalFormat("0000");
	static final int DEBUG = 0;
	static final int THREADS = 20;
	static volatile int page = 0;

	public static void main(String[] args) throws Exception {
		final File inDir = new File(args[0]);
		final File outDir = new File(args[1]);
		final String tessData = args[2];

		if (DEBUG != 0) {
			process(inDir, outDir, DEBUG, tessData);
		} else {
			Thread[] th = new Thread[THREADS];
			for (int i = 0; i < THREADS; ++i) {
				th[i] = new Thread(() -> {
					for (;;) {
						try {
							if (!process(inDir, outDir, ++page, tessData)) {
								break;
							}
						} catch (Exception e) {
							System.out.println("failed");
						}
					}
				});
				th[i].start();
			}
			for (int i = 0; i < THREADS; ++i) {
				th[i].join();
			}

		}
	}

	public static boolean process(File inDir, File outDir, int page, String tessData) throws IOException {
		// 対象ファイル
		final String pageName = FORMAT.format(page);
		final File inFile = new File(inDir, pageName + ".png");
		if (!inFile.exists()) {
			return false;
		}

		// OCR
		ITesseract ocr = new Tesseract();
		ocr.setDatapath(tessData);
		ocr.setLanguage("jpn");
		ocr.setPageSegMode(7);
		ocr.setTessVariable("user_defined_dpi", "600");

		System.out.println("処理開始:" + inFile);
		final BufferedImage orgim;
		final int w, h;
		{
			final Image image = ImageIO.read(inFile);
			if (DEBUG != 0) {
				PreviewUtils.preview(image, "処理前");
			}
			w = image.getWidth(null);
			h = image.getHeight(null);
			orgim = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
			Graphics2D g2d = (Graphics2D) orgim.getGraphics();
			g2d.drawImage(image, 0, 0, null);
		}
		
		Binarizer binr = new ThreasholdBinarizer(0x80);

		System.out.println("傾き・歪み補正");
		DeskewUtils.deskew(orgim, binr, page % 2 == 1);
		if (DEBUG != 0) {
			PreviewUtils.preview(orgim, "補正後");
		}

		System.out.println("二値化");
		BinaryImage binim = BinaryImage.toBinary(orgim, binr);
		if (DEBUG != 0) {
			PreviewUtils.preview(binim.getImage(), "二値化後");
		}

		System.out.println("カラムを解析");
		Rectangle[] columnRects = SegmentationUtils.detectColumns(binim);
		List<Rectangle> rows = new ArrayList<Rectangle>();
		for (int i = 0; i < columnRects.length; ++i) {
			Rectangle[] rects = SegmentationUtils.detectEntries(binim, columnRects[i]);
			System.out.println(
					"カラム " + i + "/" + columnRects.length + "/" + columnRects[i] + "/" + rects.length + " entries");
			rows.addAll(Arrays.asList(rects));
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
			outDir.mkdir();
			File outFile = new File(outDir, pageName + ".png");
			ImageIO.write(aim, "png", outFile);
		}
		if (DEBUG != 0) {
			PreviewUtils.preview(aim, "解析後");
		}

		// 再構成
		System.out.println("再構成");
		ImageOutputUtils.reconstruct(binim, entries, pageName, outDir, ocr);
		System.out.println("完了");
		return true;
	}
}
