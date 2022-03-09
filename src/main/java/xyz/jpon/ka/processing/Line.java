package xyz.jpon.ka.processing;

import java.awt.Rectangle;

public class Line {
	public enum Type {
		NAME("name"), NUMBER("num"), ADDRESS("addr");

		public final String code;

		private Type(String code) {
			this.code = code;
		}
	}
	public Type type;
	public Rectangle bounds;
	public String text;
	
	public Line(Type type) {
		this.type = type;
	}
}
