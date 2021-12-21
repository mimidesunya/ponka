package xyz.jpon.ka.tools;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.File;

import javax.imageio.ImageIO;

import xyz.jpon.ka.image.PreviewUtils;
import xyz.jpon.ka.processing.DetectGroups;

public class CurlTestApp {
	public static void main(String[] args) throws Exception {
		// 対象ファイル
		final File inDir = new File("H:\\電話帳\\原本\\昭和38年2月1日大阪市50音別電話番号簿");
		final File inFile = new File("H:\\電話帳\\原本\\昭和38年2月1日大阪市50音別電話番号簿\\ocr\\test.png");

		// 対象画像
		System.out.println("処理開始:" + inFile);
		final BufferedImage orgim;
		{
			final Image image = ImageIO.read(inFile);
			PreviewUtils.preview(image, "処理前");
			int w = image.getWidth(null);
			int h = image.getHeight(null);
			orgim = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
			Graphics2D g2d = (Graphics2D) orgim.getGraphics();
			g2d.drawImage(image, 0, 0, null);
		}

		System.out.println("パターンを除去・くくり記号を認識");
		DetectGroups detectRightGroups = new DetectGroups(inDir, false);
		DetectGroups detectLeftGroups = new DetectGroups(inDir, true);
		Rectangle r = new Rectangle(0, 0, orgim.getWidth(), orgim.getHeight() - 140);
		System.out.println("3/4");
		detectLeftGroups.detectGroups(orgim, r, 0, 30);
		System.out.println("4/4");
		detectRightGroups.detectGroups(orgim, r, r.width - 30, 30);

		BufferedImage aim = new BufferedImage(orgim.getWidth(null), orgim.getHeight(null), BufferedImage.TYPE_INT_RGB);
		{
			Graphics2D g2d = (Graphics2D) aim.getGraphics();
			g2d.setColor(Color.WHITE);
			g2d.fillRect(0, 0, aim.getWidth(), aim.getHeight());
			// 変換後画像
			g2d.drawImage(orgim, 0, 0, null);
			g2d.setStroke(new BasicStroke(5f));
		}
		PreviewUtils.preview(aim, "解析後");
	}
}
