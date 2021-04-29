package xyz.jpon.ka.tools;

import java.io.File;
import java.text.DecimalFormat;
import java.text.NumberFormat;
import java.util.Arrays;
import org.apache.commons.io.comparator.NameFileComparator;

public class SortFilesApp {

	public static void main(String[] args) throws Exception {
		File dir = new File("H:\\電話帳\\原本\\昭和12年4月1日現在横浜市電話番号簿");
		{
			File[] files = dir.listFiles();
			Arrays.sort(files, NameFileComparator.NAME_COMPARATOR);
			int c = 0;
			NumberFormat format = new DecimalFormat("X0000.png");
			for (File file : files) {
				if (!file.getName().endsWith(".png")) {
					continue;
				}
				System.out.println(file.getName());
				file.renameTo(new File(file.getParentFile(), format.format(++c)));
			}
		}
		{
			File[] files = dir.listFiles();
			Arrays.sort(files, NameFileComparator.NAME_COMPARATOR);
			int c = 0;
			NumberFormat format = new DecimalFormat("0000.png");
			for (File file : files) {
				if (!file.getName().endsWith(".png")) {
					continue;
				}
				System.out.println(file.getName());
				file.renameTo(new File(file.getParentFile(), format.format(++c)));
			}
		}
	}

}
