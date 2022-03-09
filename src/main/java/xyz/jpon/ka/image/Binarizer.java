package xyz.jpon.ka.image;

public interface Binarizer {

	/**
	 * ピクセルが墨であるかの判定。
	 * 
	 * @param rgb
	 * @return
	 */
	public boolean isInk(int rgb);
}
