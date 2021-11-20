package xyz.jpon.ka.image;

import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.Image;
import java.awt.RenderingHints;
import java.awt.geom.AffineTransform;

import javax.swing.JFrame;
import javax.swing.WindowConstants;

public class PreviewUtils {
	static final double SCALE = .3;

	private PreviewUtils() {
		// ignore
	}

	public static void preview(final Image image, String title) {
		@SuppressWarnings("serial")
		JFrame frame = new JFrame(title) {
			@Override
			public void paint(Graphics g) {
				Graphics2D g2d = (Graphics2D) g;
				g2d.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
				g2d.setTransform(AffineTransform.getScaleInstance(SCALE, SCALE));
				g2d.drawImage(image, 0, 0, this);
			}
		};
		frame.setSize((int) (image.getWidth(frame) * SCALE), (int) (image.getHeight(frame) * SCALE));
		frame.setDefaultCloseOperation(WindowConstants.EXIT_ON_CLOSE);
		frame.setVisible(true);
	}
}
