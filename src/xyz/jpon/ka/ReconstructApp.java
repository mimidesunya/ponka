package xyz.jpon.ka;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.text.DecimalFormat;
import java.text.NumberFormat;
import java.util.ArrayList;
import java.util.List;

import javax.imageio.ImageIO;

import net.sourceforge.tess4j.ITesseract;
import net.sourceforge.tess4j.Tesseract;
import net.sourceforge.tess4j.TesseractException;
import xyz.jpon.ka.image.PreviewUtils;
import xyz.jpon.ka.processing.AnalyzeEntry;
import xyz.jpon.ka.processing.DetectColumns;
import xyz.jpon.ka.processing.DetectEntries;
import xyz.jpon.ka.processing.DetectGroups;
import xyz.jpon.ka.processing.Entry;
import xyz.jpon.ka.processing.EraseAds;
import xyz.jpon.ka.processing.ErasePatterns;
import xyz.jpon.ka.processing.Mask;

public class ReconstructApp {
	static final NumberFormat FORMAT = new DecimalFormat("0000");
	static final int DEBUG = 227;
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

	public static boolean process(File inDir, File outDir, int page, String tessData)
			throws IOException, TesseractException {
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

		// 対象画像
		System.out.println("処理開始:" + inFile);
		final BufferedImage orgim;
		{
			final Image image = ImageIO.read(inFile);
			if (DEBUG != 0) {
				PreviewUtils.preview(image, "処理前");
			}
			int w = image.getWidth(null);
			int h = image.getHeight(null);
			orgim = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
			Graphics2D g2d = (Graphics2D) orgim.getGraphics();
			g2d.drawImage(image, 0, 0, null);
		}

		System.out.println("カラムを解析");
		DetectColumns detectColumns = new DetectColumns(inDir);
		Rectangle[] columnRects = detectColumns.detectColumns(orgim, 4, 1020);

		System.out.println("カラムを処理");
		EraseAds eraseAds = new EraseAds(inDir);
		ErasePatterns erasePatterns1 = new ErasePatterns(
				new Mask[] { Mask.createMask(new File(inDir, "ocr/dots-mask.png"), .92),
						Mask.createMask(new File(inDir, "ocr/del1.png"), .85),
						Mask.createMask(new File(inDir, "ocr/del5.png"), .85),
						Mask.createMask(new File(inDir, "ocr/del2.png"), .80),
						Mask.createMask(new File(inDir, "ocr/del6.png"), .85),
						Mask.createMask(new File(inDir, "ocr/del7.png"), .85) });
		ErasePatterns erasePatterns2 = new ErasePatterns(
				new Mask[] { Mask.createMask(new File(inDir, "ocr/del3.png"), .85),
						Mask.createMask(new File(inDir, "ocr/del4.png"), .85) });
		DetectGroups detectRightGroups = new DetectGroups(inDir, false);
		DetectGroups detectLeftGroups = new DetectGroups(inDir, true);
		int markerWidth = 30;
		List<Rectangle> entries = new ArrayList<Rectangle>();
		for (Rectangle column : columnRects) {
			// 広告除去
			eraseAds.eraseAds(orgim, column);
			System.out.println(column);
			// パターン除去
			System.out.println("1/4");
			erasePatterns1.erasePatterns(orgim, new Rectangle(column.x, column.y, column.width / 2, column.height));
			System.out.println("2/4");
			erasePatterns2.erasePatterns(orgim,
					new Rectangle(column.x + column.width / 2, column.y, column.width / 5, column.height));
			// くくり記号除去
			System.out.println("3/4");
			detectLeftGroups.detectGroups(orgim,
					new Rectangle(column.x + column.width / 4, column.y, column.width / 4, column.height), column.x,
					markerWidth);
			System.out.println("4/4");
			detectRightGroups.detectGroups(orgim,
					new Rectangle(column.x + column.width / 2, column.y, column.width / 4, column.height),
					column.x + column.width - markerWidth, markerWidth);
			DetectEntries.detectEntries(orgim, column, entries);
			break;
		}

//		BufferedImage blurred;
//		{
//			int radius = 10;
//			int size = radius * 2 + 1;
//			float weight = 1.0f / (size * size);
//			float[] data = new float[size * size];
//
//			for (int i = 0; i < data.length; i++) {
//				data[i] = weight;
//			}
//			Kernel kernel = new Kernel(size, size, data);
//			BufferedImageOp op = new ConvolveOp(kernel, ConvolveOp.EDGE_NO_OP, null);
//			blurred = op.filter(orgim, null);
//			PreviewUtils.preview(blurred, "二値化");
//		}

		System.out.println("エントリを解析");
		List<Entry> analyzedEntries = new ArrayList<Entry>();
		AnalyzeEntry analyzeEntry = new AnalyzeEntry(inDir);
		for (Rectangle entry : entries) {
			Entry analyzedEntry = analyzeEntry.analyzeEntry(orgim, entry);
			if (analyzedEntry != null) {
				analyzedEntries.add(analyzedEntry);
			}
		}

		BufferedImage binim;
		{
			int w = orgim.getWidth(null);
			int h = orgim.getHeight(null);
			binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			Graphics2D g2d = (Graphics2D) binim.getGraphics();
			g2d.drawImage(orgim, 0, 0, w, h, null);
		}

		Rectangle column = columnRects[0];
		String imageName = pageName + ".png";
		File outFile = new File(outDir, imageName);
		File outHtmlFile = new File(outDir, pageName + ".html");
		BufferedImage aim = new BufferedImage(orgim.getWidth(null), orgim.getHeight(null), BufferedImage.TYPE_INT_RGB);
		try(PrintWriter out = new PrintWriter(new OutputStreamWriter(new FileOutputStream(outHtmlFile), "UTF-8"))){
			out.println("<html><style>");
			out.println(".ocr {");
			out.printf("background-image: url(%s);", imageName);
			out.printf("background-position: %dpx %dpx;", -column.x, -column.y);
			out.printf("width: %dpx; height:%dpx;", column.width, column.height);
			out.println("transform-origin: top left;");
			out.println("transform: scale(.5);");
			out.println("}");
			
			out.println(".ocr span {");
			out.println("position: absolute;");
			out.println("font-size: 40px;");
			out.printf("transform: translate(%dpx, %dpx);", -column.x + column.width, -column.y);
			out.println("border:1px solid;");
			out.println("}");
			out.println(".ocr .name {border-color: Blue;}");
			out.println(".ocr .num {border-color: Red;}");
			out.println(".addr .name {border-color: Green;}");
			out.println("</style><body><div class=\"ocr\">");
			Graphics2D g2d = (Graphics2D) aim.getGraphics();
			g2d.setColor(Color.WHITE);
			g2d.fillRect(0, 0, aim.getWidth(), aim.getHeight());
			// 変換後画像
			g2d.drawImage(orgim, 0, 0, null);
			g2d.setStroke(new BasicStroke(2f));

			g2d.setColor(Color.RED);
			for (Rectangle r : columnRects) {
				g2d.draw(r);
			}
			for (Rectangle r : entries) {
				g2d.draw(r);
			}

			for (Entry e : analyzedEntries) {
				g2d.setColor(Color.RED);
				g2d.draw(e.bounds);
				g2d.setColor(Color.BLUE);
				for (Rectangle r : e.names) {
					ocr("name", binim, r, ocr, out);
					g2d.draw(r);
				}
				g2d.setColor(Color.BLACK);
				for (Rectangle r : e.nums) {
					ocr("num", binim, r, ocr, out);
					g2d.draw(r);
				}
				g2d.setColor(Color.GREEN);
				for (Rectangle r : e.addrs) {
					ocr("addr", binim, r, ocr, out);
					g2d.draw(r);
				}
			}
			out.println("</div></body></html>");
		}
		outDir.mkdir();
		ImageIO.write(aim, "png", outFile);
		
		if (DEBUG != 0) {
			PreviewUtils.preview(aim, "解析後");
		}
		return true;
	}
	
	public static void ocr(String clazz, BufferedImage binim, Rectangle r, ITesseract ocr, PrintWriter out)
			throws IOException, TesseractException {
		BufferedImage im = binim.getSubimage(r.x, r.y, r.width, r.height);
		String text = ocr.doOCR(im);
		text = text.trim();
		out.printf("<span class=\"%s\" style=\"left:%dpx;top:%dpx;width:%dpx;height:%dpx;\">%s</span>",
				clazz, r.x, r.y, r.width, r.height, text);
		out.println();
	}
}
