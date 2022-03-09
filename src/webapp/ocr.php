<!DOCTYPE html>
<html lang="ja">
  <head>
    <meta charset="utf-8">
    <link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/meyer-reset/2.0/reset.min.css" media="screen,print">
    <title>OCR</title>
    <style>
#content {
    display: flex;
    width: 100%;
}
#image, #work {
    width: 50%;
}
#work {
    position: relative;
    transform-origin: top left;
}
#work span {
    position: absolute;
    white-space: nowrap;
    border: 3px solid;
}
#work span.num {
    border-color: Red;
}
#work span.name {
    border-color: Maroon;
}
#work span.addr {
    border-color: Fuchsia;
}

    </style>
    <script>
const base = 'data/oo19630201/ocr/';
const page = '0225';

function drawRect(ctx, bounds, x, y) {
	ctx.strokeRect(bounds.x + x, bounds.y + y, bounds.width, bounds.height);
}

function draw(im, json) {
	const canvas = document.getElementById('image');
	const work = document.getElementById('work');
	const ctx = canvas.getContext('2d');

	let ch = 0, cw = 0;
	for (let column of json.columns) {
		if (column.bounds.width > cw) {
			cw = column.bounds.width;
		}
		ch += column.bounds.height;
	}
	canvas.width = cw;
	canvas.height = ch;

	ctx.lineWidth = 3;
	let y = 0;
	//カラム
	for (let column of json.columns) {
		// 処理画像
		ctx.drawImage(im, column.bounds.x, column.bounds.y, column.bounds.width, column.bounds.height,
				0, y, column.bounds.width, column.bounds.height);

		// エントリ
		for (let entry of column.entries) {
			for (let line of entry.lines) {
				switch(line.type) {
				case 'num':
					ctx.strokeStyle = 'Red';
					break;
				case 'name':
					ctx.strokeStyle = 'Maroon';
					break;
				case 'addr':
					ctx.strokeStyle = 'Fuchsia';
					break;
				}
				drawRect(ctx, line.bounds, -column.bounds.x, -column.bounds.y + y);
				let tx = line.bounds.x - column.bounds.x;
				let ty = line.bounds.y - column.bounds.y + y;
				let th = line.bounds.height;
				work.innerHTML += '<span class="'+line.type+'" style="left:'+tx+'px;top:'+ty+'px;font-size:'+th+'px;">'+line.text+'</span>';
			}
			
			//ctx.strokeStyle = 'Green';
			//drawRect(ctx, entry.bounds, -column.bounds.x, -column.bounds.y + y);
		}
		// 広告
// 		for (let ad of column.ads) {
// 			ctx.strokeStyle = 'Olive';
// 			drawRect(ctx, ad, -column.bounds.x, -column.bounds.y + y);
// 		}
		
		y += column.bounds.height;
	}

	window.onresize();
}

window.onload = () => {
	window.onresize = () => {
		const canvas = document.getElementById('image');
		const work = document.getElementById('work');
		let s = canvas.getBoundingClientRect().width / canvas.width;
		work.style.transform = 'scale('+s+')';
	};

	const im = new Image();
	im.onload = () => {		
		let xhr = new XMLHttpRequest();
		xhr.open('GET', base+page+'.json');
		xhr.onload = () => {
			let json = JSON.parse(xhr.response);
			console.log(json);
			draw(im, json);
		};
		xhr.send();
	};
	im.src = base+page+'.png';
}
    </script>
  </head>
  <body>
    <div id="content">
      <canvas id="image"></canvas>
      <div id="work"></div>
    </div>
  </body>
</html>
