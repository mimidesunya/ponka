package xyz.jpon.ka.image;

public class ThreasholdBinarizer implements Binarizer {
	protected final int threashold;
	
	public ThreasholdBinarizer(int threashold) {
		this.threashold = threashold;
	}

	/**
	 * ピクセルが墨であるかの判定。
	 * 
	 * @param rgb
	 * @return
	 */
	public boolean isInk(int rgb) {
		int r = (rgb >> 16) & 0xFF;
		int g = (rgb >> 8) & 0xFF;
		int b = (rgb >> 0) & 0xFF;
		return (r + g + b) / 3 < this.threashold;
	}
}
