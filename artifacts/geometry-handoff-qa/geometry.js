//#region apps/web/src/geometryHandoff.ts
var e = 128, t = 160, n = 17, r = 21, i = (e, t, n) => Math.max(t, Math.min(n, e)), a = (e) => {
	let t = i(e, 0, 1);
	return t * t * (3 - 2 * t);
}, o = (e, t, n) => e[i(n, 0, 159) * 128 + i(t, 0, 127)];
function s(e) {
	let t = 0;
	for (let n = 0; n < 20; n++) for (let r = 0; r < 16; r++) {
		let i = (n * 17 + r) * 2;
		for (let n = 0; n < 2; n++) t = Math.max(t, (Math.abs(e[i + 2 + n] - e[i + n]) + Math.abs(e[i + 34 + n] - e[i + n])) / 8);
	}
	if (t > .6) for (let n = 0; n < e.length; n++) e[n] *= .6 / t;
	return e;
}
function c(e, t) {
	if (e.every((e, n) => e === t[n])) return {
		xy: /* @__PURE__ */ new Float32Array(714),
		reliable: 1,
		residual: 0,
		peak: 0
	};
	let n = (n, r, i, a, s = 3) => {
		let c = 0;
		for (let l = -s; l <= s; l += 2) for (let u = -s; u <= s; u += 2) {
			let s = o(e, n + u, r + l) - o(t, n + u + i, r + l + a);
			c += Math.min(1600, s * s);
		}
		return c / ((s + 1) * (s + 1));
	}, r = (n, r) => {
		let i = 0;
		for (let a = 32; a < 100; a += 8) for (let s = 32; s < 96; s += 8) {
			let c = o(e, s, a) - o(t, s + n, a + r);
			i += Math.min(1600, c * c);
		}
		return i;
	}, c = 0, l = 0, u = r(0, 0);
	for (let e = -8; e <= 8; e++) for (let t = -8; t <= 8; t++) {
		let n = r(t, e);
		n < u && (u = n, c = t, l = e);
	}
	let d = /* @__PURE__ */ new Float32Array(714), f = /* @__PURE__ */ new Float32Array(357), p = 0, m = 0, h = 0;
	for (let t = 1; t < 20; t++) for (let r = 1; r < 16; r++) {
		let a = r * 8, s = t * 8, u = t * 17 + r, g = c, _ = l, v = n(a, s, c, l);
		for (let e = l - 3; e <= l + 3; e++) for (let t = c - 3; t <= c + 3; t++) {
			let r = n(a, s, t, e) + .8 * ((t - c) ** 2 + (e - l) ** 2);
			r < v && (v = r, g = t, _ = e);
		}
		let y = n(a, s, g, _), b = (e, t) => i(.5 * (e - t) / Math.max(1e-5, e + t - 2 * y), -.5, .5), x = b(n(a, s, g - 1, _), n(a, s, g + 1, _)), S = b(n(a, s, g, _ - 1), n(a, s, g, _ + 1)), C = 0;
		for (let t = -2; t <= 2; t++) C += Math.abs(o(e, a + t + 1, s) - o(e, a + t - 1, s)) + Math.abs(o(e, a, s + t + 1) - o(e, a, s + t - 1));
		let w = C > 35 && y < 450;
		f[u] = +!!w, d[u * 2] = w ? g + x : c, d[u * 2 + 1] = w ? _ + S : l, a >= 24 && a <= 104 && s >= 24 && s <= 128 && (m++, w && p++, h += y);
	}
	let g = new Float32Array(d.length), _ = 0;
	for (let e = 1; e < 20; e++) for (let t = 1; t < 16; t++) {
		let n = e * 17 + t;
		for (let r = 0; r < 2; r++) {
			let o = 0, s = 0;
			for (let i = Math.max(1, e - 1); i <= Math.min(19, e + 1); i++) for (let e = Math.max(1, t - 1); e <= Math.min(15, t + 1); e++) {
				let t = i * 17 + e, a = (t === n ? 3 : 1) * (f[t] ? 1 : .2);
				o += d[t * 2 + r] * a, s += a;
			}
			let c = a(t / 2) * a((16 - t) / 2) * a(e / 2) * a((20 - e) / 2);
			g[n * 2 + r] = i(o / s, -10, 10) * c, _ = Math.max(_, Math.abs(g[n * 2 + r]));
		}
	}
	return s(g), {
		xy: g,
		reliable: p / Math.max(1, m),
		residual: h / Math.max(1, m),
		peak: _
	};
}
var l = "\nprecision highp float;\nvarying vec2 uv;\nuniform sampler2D firstImage,secondImage,flowImage;\nuniform float progress;\nuniform vec2 imageSize;\nvec4 sharpSample(sampler2D image,vec2 point) {\n  vec2 pixel=point*imageSize-0.5,base=floor(pixel),fraction=pixel-base;\n  vec2 f=fraction;\n  vec2 w0=f*(-0.5+f*(1.0-0.5*f));\n  vec2 w1=1.0+f*f*(-2.5+1.5*f);\n  vec2 w2=f*(0.5+f*(2.0-1.5*f));\n  vec2 w3=f*f*(-0.5+0.5*f),w12=w1+w2;\n  // Exact Catmull-Rom with 9 bilinear fetches rather than 16 point fetches.\n  vec2 p0=(base-0.5)/imageSize,p12=(base+0.5+w2/w12)/imageSize,p3=(base+2.5)/imageSize;\n  vec4 color=texture2D(image,vec2(p0.x,p0.y))*w0.x*w0.y\n    +texture2D(image,vec2(p12.x,p0.y))*w12.x*w0.y\n    +texture2D(image,vec2(p3.x,p0.y))*w3.x*w0.y\n    +texture2D(image,vec2(p0.x,p12.y))*w0.x*w12.y\n    +texture2D(image,p12)*w12.x*w12.y\n    +texture2D(image,vec2(p3.x,p12.y))*w3.x*w12.y\n    +texture2D(image,vec2(p0.x,p3.y))*w0.x*w3.y\n    +texture2D(image,vec2(p12.x,p3.y))*w12.x*w3.y\n    +texture2D(image,p3)*w3.x*w3.y;\n  return clamp(color,0.0,1.0);\n}\nvec2 flow(vec2 p) {\n  // Grid vertices span [0,1], whereas texture samples address texel centers.\n  vec2 grid=(clamp(p,0.0,1.0)*vec2(16.0,20.0)+0.5)/vec2(17.0,21.0);\n  vec4 v=texture2D(flowImage,grid)*255.0;\n  return ((vec2(v.r*256.0+v.g,v.b*256.0+v.a)/65535.0)*24.0-12.0)/vec2(128.0,160.0);\n}\nvoid main() {\n  // Invert the intermediate warp with two fixed-point iterations.\n  vec2 p=uv-progress*flow(uv);\n  p=uv-progress*flow(p);\n  vec4 color;\n  if(progress<0.5) color=sharpSample(firstImage,clamp(p,0.0,1.0));\n  else color=sharpSample(secondImage,clamp(p+flow(p),0.0,1.0));\n  gl_FragColor=vec4(color.rgb,1.0);\n}", u = class {
	canvas = document.createElement("canvas");
	gl;
	program;
	textures = [];
	constructor() {
		let e = this.canvas.getContext("webgl", {
			alpha: !1,
			antialias: !1,
			preserveDrawingBuffer: !0
		});
		if (!e) throw Error("WebGL unavailable");
		this.gl = e;
		let t = (t, n) => {
			let r = e.createShader(t);
			if (e.shaderSource(r, n), e.compileShader(r), !e.getShaderParameter(r, e.COMPILE_STATUS)) throw Error(e.getShaderInfoLog(r) ?? "shader");
			return r;
		}, n = e.createProgram();
		if (e.attachShader(n, t(e.VERTEX_SHADER, "attribute vec2 position; varying vec2 uv; void main(){gl_Position=vec4(position,0.,1.);uv=vec2((position.x+1.)*.5,(1.-position.y)*.5);}")), e.attachShader(n, t(e.FRAGMENT_SHADER, l)), e.linkProgram(n), !e.getProgramParameter(n, e.LINK_STATUS)) throw Error("Handoff shader link failed");
		this.program = n, e.useProgram(n);
		let r = e.createBuffer();
		e.bindBuffer(e.ARRAY_BUFFER, r), e.bufferData(e.ARRAY_BUFFER, new Float32Array([
			-1,
			-1,
			1,
			-1,
			-1,
			1,
			1,
			1
		]), e.STATIC_DRAW);
		let i = e.getAttribLocation(n, "position");
		e.enableVertexAttribArray(i), e.vertexAttribPointer(i, 2, e.FLOAT, !1, 0, 0);
		for (let t = 0; t < 3; t++) this.textures.push(e.createTexture()), e.activeTexture(e.TEXTURE0 + t), e.bindTexture(e.TEXTURE_2D, this.textures[t]), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_MIN_FILTER, e.LINEAR), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_MAG_FILTER, e.LINEAR), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_WRAP_S, e.CLAMP_TO_EDGE), e.texParameteri(e.TEXTURE_2D, e.TEXTURE_WRAP_T, e.CLAMP_TO_EDGE), e.uniform1i(e.getUniformLocation(n, [
			"firstImage",
			"secondImage",
			"flowImage"
		][t]), t);
	}
	render(e, t, n, r, a, o) {
		let s = this.gl;
		if (s.isContextLost()) throw Error("Handoff GPU context lost");
		(this.canvas.width !== a || this.canvas.height !== o) && (this.canvas.width = a, this.canvas.height = o), s.viewport(0, 0, a, o), s.useProgram(this.program);
		for (let [n, r] of [e, t].entries()) s.activeTexture(s.TEXTURE0 + n), s.bindTexture(s.TEXTURE_2D, this.textures[n]), s.texImage2D(s.TEXTURE_2D, 0, s.RGBA, s.RGBA, s.UNSIGNED_BYTE, r);
		let c = /* @__PURE__ */ new Uint8Array(1428);
		for (let e = 0; e < n.length; e++) {
			let t = Math.round((i(n[e], -12, 12) + 12) / 24 * 65535);
			c[e * 2] = t >> 8, c[e * 2 + 1] = t & 255;
		}
		return s.activeTexture(s.TEXTURE2), s.bindTexture(s.TEXTURE_2D, this.textures[2]), s.texImage2D(s.TEXTURE_2D, 0, s.RGBA, 17, 21, 0, s.RGBA, s.UNSIGNED_BYTE, c), s.uniform1f(s.getUniformLocation(this.program, "progress"), r), s.uniform2f(s.getUniformLocation(this.program, "imageSize"), a, o), s.drawArrays(s.TRIANGLE_STRIP, 0, 4), this.canvas;
	}
}, d = null;
function f(e) {
	try {
		if (d && !d.gl.isContextLost()) return;
		let t = d = new u();
		t.render(e, e, /* @__PURE__ */ new Float32Array(714), .25, e.width, e.height), t.gl.finish();
		let n = /* @__PURE__ */ new Float32Array(20480), r = new Float32Array(n.length);
		for (let e = 0; e < 160; e++) for (let t = 0; t < 128; t++) n[e * 128 + t] = 110 + 40 * Math.sin(t * .4) + 30 * Math.sin(e * .53), r[e * 128 + t] = 110 + 40 * Math.sin((t - 2) * .4) + 30 * Math.sin((e - 1) * .53);
		c(n, r), c(r, n);
	} catch {
		d = null;
	}
}
var p = class {
	sampleCanvas = null;
	previous = null;
	stats = {
		mode: "pending",
		frames: 0,
		peak_ms: 0,
		reliable: 0,
		residual: 0,
		peak_displacement: 0,
		fallback_frames: 0,
		last_error: ""
	};
	sample(e) {
		let t = this.sampleCanvas ??= document.createElement("canvas");
		t.width !== 128 && (t.width = 128, t.height = 160);
		let n = t.getContext("2d", { willReadFrequently: !0 });
		n.drawImage(e, 0, 0, 128, 160);
		let r = n.getImageData(0, 0, 128, 160).data, i = /* @__PURE__ */ new Float32Array(20480);
		for (let e = 0; e < i.length; e++) i[e] = r[e * 4] * .299 + r[e * 4 + 1] * .587 + r[e * 4 + 2] * .114;
		return i;
	}
	draw(e, t, n, r) {
		let i = e.canvas.width, a = e.canvas.height;
		if (r <= 0 || r >= 1) {
			e.drawImage(r <= 0 ? t : n, 0, 0, i, a);
			return;
		}
		let o = performance.now();
		try {
			let o = c(this.sample(t), this.sample(n));
			if (o.reliable < .15 || o.residual > 800) throw Error("Unreliable frame correspondence");
			if (this.previous) for (let e = 0; e < o.xy.length; e++) o.xy[e] = .7 * o.xy[e] + .3 * this.previous[e];
			this.previous = o.xy, d?.gl.isContextLost() && (d = null);
			let s = d ??= new u();
			e.drawImage(s.render(t, n, o.xy, r, i, a), 0, 0, i, a), this.stats = {
				...this.stats,
				mode: "single_texture_warp",
				reliable: o.reliable,
				residual: o.residual,
				peak_displacement: o.peak
			};
		} catch (o) {
			e.drawImage(r < .5 ? t : n, 0, 0, i, a), this.stats.mode = "unwarped_switch", this.stats.fallback_frames++, this.stats.last_error = o instanceof Error ? o.message : "render_failed";
		}
		this.stats.frames++, this.stats.peak_ms = Math.max(this.stats.peak_ms, performance.now() - o);
	}
};
//#endregion
export { t as FLOW_H, e as FLOW_W, r as GRID_H, n as GRID_W, p as GeometryHandoff, l as HANDOFF_FRAGMENT, s as boundFlow, c as matchGeometry, f as warmGeometryHandoff };
