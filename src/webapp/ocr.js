function drawRect(ctx, bounds) {
	ctx.strokeRect(bounds[0], bounds[1], bounds[2], bounds[3]);
}

window.onload = () => {
	const im = new Image();
	im.onload = () => {
		const canvas = document.getElementById('main');
		const ctx = canvas.getContext('2d');
		canvas.width = im.width;
		canvas.height = im.height;
		ctx.drawImage(im, 0, 0, canvas.width, canvas.height);
		
		let xhr = new XMLHttpRequest();
		xhr.open('GET', 'data/oo19630201/ocr/0225.json');
		xhr.onload = () => {
			let json = JSON.parse(xhr.response);
			ctx.lineWidth = 2;
			ctx.strokeStyle = 'Red';
			for (let column of json.columns) {
				drawRect(ctx, column.bounds);
			}
		};
		xhr.send();
	};
	im.src = 'data/oo19630201/ocr/0225.png';
}
