package xyz.jpon.ka;

import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.text.DecimalFormat;
import java.text.NumberFormat;
import java.util.ArrayList;
import java.util.List;

import javax.imageio.ImageIO;
import javax.json.Json;
import javax.json.JsonArrayBuilder;
import javax.json.JsonObject;
import javax.json.JsonObjectBuilder;
import javax.json.JsonWriter;

import net.sourceforge.tess4j.ITesseract;
import net.sourceforge.tess4j.Tesseract;
import net.sourceforge.tess4j.TesseractException;
import xyz.jpon.ka.image.PreviewUtils;
import xyz.jpon.ka.processing.AnalyzeEntry;
import xyz.jpon.ka.processing.Column;
import xyz.jpon.ka.processing.DetectColumns;
import xyz.jpon.ka.processing.DetectEntries;
import xyz.jpon.ka.processing.DetectGroups;
import xyz.jpon.ka.processing.Entry;
import xyz.jpon.ka.processing.EraseAds;
import xyz.jpon.ka.processing.ErasePatterns;
import xyz.jpon.ka.processing.Line;
import xyz.jpon.ka.processing.Mask;

public class ReconstructApp {
	static final NumberFormat FORMAT = new DecimalFormat("0000");
	static final int DEBUG = 225;
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
		// ??????????????????
		final String pageName = FORMAT.format(page);
		final File inFile = new File(inDir, pageName + ".png");
		if (!inFile.exists()) {
			return false;
		}

		// OCR
		ITesseract ocr = new Tesseract();
		ocr.setDatapath(tessData);
		ocr.setLanguage("jpn");
		ocr.setPageSegMode(6);
		ocr.setTessVariable("user_defined_dpi", "600");
		ocr.setTessVariable("preserve_interword_spaces", "1");

		// ????????????
		System.out.println("????????????:" + inFile);

		Rectangle[] columnRects;
		BufferedImage binim;
		{
			final Image image = ImageIO.read(inFile);
			if (DEBUG != 0) {
				PreviewUtils.preview(image, "?????????");
			}
			int w = image.getWidth(null);
			int h = image.getHeight(null);
			BufferedImage orgim = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
			{
				Graphics2D g2d = (Graphics2D) orgim.getGraphics();
				g2d.drawImage(image, 0, 0, null);
			}

			System.out.println("??????????????????");
			DetectColumns detectColumns = new DetectColumns(inDir);
			columnRects = detectColumns.detectColumns(orgim, 4, 1020);

			binim = new BufferedImage(w, h, BufferedImage.TYPE_BYTE_BINARY);
			{
				Graphics2D g2d = (Graphics2D) binim.getGraphics();
				g2d.drawImage(orgim, 0, 0, w, h, null);
			}
		}

		System.out.println("??????????????????");
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
		List<Column> columns = new ArrayList<Column>();
		for (Rectangle rect : columnRects) {
			Column column = new Column();
			column.bounds = rect;
			List<Entry> entries = new ArrayList<Entry>();
			// ????????????
			column.ads = eraseAds.eraseAds(binim, rect);
			System.out.println(rect);

			// ??????????????????
			System.out.println("1/4");
			erasePatterns1.erasePatterns(binim, new Rectangle(rect.x, rect.y, rect.width / 2, rect.height));
			System.out.println("2/4");
			erasePatterns2.erasePatterns(binim,
					new Rectangle(rect.x + rect.width / 2, rect.y, rect.width / 5, rect.height));
			// ?????????????????????
			System.out.println("3/4");
			detectLeftGroups.detectGroups(binim,
					new Rectangle(rect.x + rect.width / 4, rect.y, rect.width / 4, rect.height), rect.x, markerWidth);
			System.out.println("4/4");
			detectRightGroups.detectGroups(binim,
					new Rectangle(rect.x + rect.width / 2, rect.y, rect.width / 4, rect.height),
					rect.x + rect.width - markerWidth, markerWidth);

			// ??????????????????
			DetectEntries.detectEntries(binim, rect, entries);
			column.entries = entries.toArray(new Entry[entries.size()]);
			columns.add(column);

			// ??????????????????
			List<Entry> analyzedEntries = new ArrayList<Entry>();
			AnalyzeEntry analyzeEntry = new AnalyzeEntry(inDir);
			for (Entry entry : column.entries) {
				Entry analyzedEntry = analyzeEntry.analyzeEntry(binim, entry);
				if (analyzedEntry != null) {
					analyzedEntries.add(analyzedEntry);
				}
			}
			column.entries = analyzedEntries.toArray(new Entry[analyzedEntries.size()]);
		}

		// ????????????????????????
		String imageName = pageName + ".png";
		File outFile = new File(outDir, imageName);
		outDir.mkdir();
		ImageIO.write(binim, "png", outFile);

		// ??????????????????
		File outJsonFile = new File(outDir, pageName + ".json");
		try (OutputStream out = new FileOutputStream(outJsonFile)) {
			JsonWriter jw = Json.createWriter(out);
			JsonObjectBuilder jsonImage = Json.createObjectBuilder();
			// ??????????????????
			jsonImage.add("width", binim.getWidth());
			jsonImage.add("height", binim.getHeight());

			// ?????????????????????
			JsonArrayBuilder jsonColumns = Json.createArrayBuilder();
			for (Column column : columns) {
				JsonObjectBuilder jsonColumn = Json.createObjectBuilder();
				jsonColumn.add("bounds", createRect(column.bounds));
				JsonArrayBuilder jsonAds = Json.createArrayBuilder();
				for (Rectangle ad : column.ads) {
					jsonAds.add(createRect(ad));
				}
				JsonArrayBuilder jsonEntries = Json.createArrayBuilder();
				for (Entry e : column.entries) {
					JsonObjectBuilder jsonEntry = Json.createObjectBuilder();
					jsonEntry.add("bounds", createRect(e.bounds));
					JsonArrayBuilder jsonLines = Json.createArrayBuilder();
					for (Line l : e.lines) {
						ocr("name", binim, l, ocr);
						jsonLines.add(Json.createObjectBuilder().add("type", l.type.code)
								.add("bounds", createRect(l.bounds)).add("text", l.text).build());
					}
					jsonEntry.add("lines", jsonLines);
					jsonEntries.add(jsonEntry.build());
				}
				jsonColumn.add("entries", jsonEntries.build());
				jsonColumn.add("ads", jsonAds.build());
				jsonColumns.add(jsonColumn.build());
			}

			jsonImage.add("columns", jsonColumns.build());
			jw.writeObject(jsonImage.build());
		}

		if (DEBUG != 0) {
			PreviewUtils.preview(binim, "????????????");
		}
		return true;
	}

	private static JsonObject createRect(Rectangle rect) {
		return Json.createObjectBuilder().add("x", rect.x).add("y", rect.y).add("width", rect.width)
				.add("height", rect.height).build();
	}

	public static void ocr(String clazz, BufferedImage binim, Line l, ITesseract ocr)
			throws IOException, TesseractException {
		BufferedImage im = binim.getSubimage(l.bounds.x, l.bounds.y, l.bounds.width, l.bounds.height);
		String text = ocr.doOCR(im);
		text = text.trim();
		l.text = text;
//		out.printf("<span class=\"%s\" style=\"left:%dpx;top:%dpx;width:%dpx;height:%dpx;\">%s</span>",
//				clazz, r.x, r.y, r.width, r.height, text);
//		out.println();
	}
}
