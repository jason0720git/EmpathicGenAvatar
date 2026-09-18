//#region apps/web/src/geometryHandoff.ts
var e = 128, t = 160, n = 17, r = 21, i = (e, t, n) => Math.max(t, Math.min(n, e)), a = (e) => {
	let t = i(e, 0, 1);
	return t * t * (3 - 2 * t);
}, o = (e) => a((e - .2) / .6);
function s(e, t) {
	for (let n = 0; n < e.length; n++) e[n] = t[n] + i(.7 * (e[n] - t[n]), -.35, .35);
	return l(e);
}
var c = (e, t, n) => e[i(n, 0, 159) * 128 + i(t, 0, 127)];
function l(e) {
	let t = 0;
	for (let n = 0; n < 20; n++) for (let r = 0; r < 16; r++) {
		let i = (n * 17 + r) * 2;
		for (let n = 0; n < 2; n++) t = Math.max(t, (Math.abs(e[i + 2 + n] - e[i + n]) + Math.abs(e[i + 34 + n] - e[i + n])) / 8);
	}
	if (t > .6) for (let n = 0; n < e.length; n++) e[n] *= .6 / t;
	return e;
}
function u(e, t) {
	if (e.every((e, n) => e === t[n])) return {
		xy: /* @__PURE__ */ new Float32Array(714),
		reliable: 1,
		residual: 0,
		peak: 0
	};
	let n = (n, r, i, a, o = 3) => {
		let s = 0;
		for (let l = -o; l <= o; l += 2) for (let u = -o; u <= o; u += 2) {
			let o = c(e, n + u, r + l) - c(t, n + u + i, r + l + a);
			s += Math.min(1600, o * o);
		}
		return s / ((o + 1) * (o + 1));
	}, r = (n, r) => {
		let i = 0;
		for (let a = 32; a < 100; a += 8) for (let o = 32; o < 96; o += 8) {
			let s = c(e, o, a) - c(t, o + n, a + r);
			i += Math.min(1600, s * s);
		}
		return i;
	}, o = 0, s = 0, u = r(0, 0);
	for (let e = -8; e <= 8; e++) for (let t = -8; t <= 8; t++) {
		let n = r(t, e);
		n < u && (u = n, o = t, s = e);
	}
	let d = /* @__PURE__ */ new Float32Array(714), f = /* @__PURE__ */ new Float32Array(357), p = 0, m = 0, h = 0;
	for (let t = 1; t < 20; t++) for (let r = 1; r < 16; r++) {
		let a = r * 8, l = t * 8, u = t * 17 + r, g = o, _ = s, v = n(a, l, o, s);
		for (let e = s - 3; e <= s + 3; e++) for (let t = o - 3; t <= o + 3; t++) {
			let r = n(a, l, t, e) + .8 * ((t - o) ** 2 + (e - s) ** 2);
			r < v && (v = r, g = t, _ = e);
		}
		let y = n(a, l, g, _), b = (e, t) => i(.5 * (e - t) / Math.max(1e-5, e + t - 2 * y), -.5, .5), x = b(n(a, l, g - 1, _), n(a, l, g + 1, _)), S = b(n(a, l, g, _ - 1), n(a, l, g, _ + 1)), C = 0;
		for (let t = -2; t <= 2; t++) C += Math.abs(c(e, a + t + 1, l) - c(e, a + t - 1, l)) + Math.abs(c(e, a, l + t + 1) - c(e, a, l + t - 1));
		let w = C > 35 && y < 450;
		f[u] = +!!w, d[u * 2] = w ? g + x : o, d[u * 2 + 1] = w ? _ + S : s, a >= 24 && a <= 104 && l >= 24 && l <= 128 && (m++, w && p++, h += y);
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
	return l(g), {
		xy: g,
		reliable: p / Math.max(1, m),
		residual: h / Math.max(1, m),
		peak: _
	};
}
var d = "\nprecision highp float;\nvarying vec2 uv;\nuniform sampler2D firstImage,secondImage,flowImage;\nuniform float progress;\nuniform vec2 imageSize;\nvec4 sharpSample(sampler2D image,vec2 point) {\n  vec2 pixel=point*imageSize-0.5,base=floor(pixel),fraction=pixel-base;\n  vec2 f=fraction;\n  vec2 w0=f*(-0.5+f*(1.0-0.5*f));\n  vec2 w1=1.0+f*f*(-2.5+1.5*f);\n  vec2 w2=f*(0.5+f*(2.0-1.5*f));\n  vec2 w3=f*f*(-0.5+0.5*f),w12=w1+w2;\n  // Exact Catmull-Rom with 9 bilinear fetches rather than 16 point fetches.\n  vec2 p0=(base-0.5)/imageSize,p12=(base+0.5+w2/w12)/imageSize,p3=(base+2.5)/imageSize;\n  vec4 color=texture2D(image,vec2(p0.x,p0.y))*w0.x*w0.y\n    +texture2D(image,vec2(p12.x,p0.y))*w12.x*w0.y\n    +texture2D(image,vec2(p3.x,p0.y))*w3.x*w0.y\n    +texture2D(image,vec2(p0.x,p12.y))*w0.x*w12.y\n    +texture2D(image,p12)*w12.x*w12.y\n    +texture2D(image,vec2(p3.x,p12.y))*w3.x*w12.y\n    +texture2D(image,vec2(p0.x,p3.y))*w0.x*w3.y\n    +texture2D(image,vec2(p12.x,p3.y))*w12.x*w3.y\n    +texture2D(image,p3)*w3.x*w3.y;\n  return clamp(color,0.0,1.0);\n}\nvec2 flow(vec2 p) {\n  // Grid vertices span [0,1], whereas texture samples address texel centers.\n  vec2 grid=(clamp(p,0.0,1.0)*vec2(16.0,20.0)+0.5)/vec2(17.0,21.0);\n  vec4 v=texture2D(flowImage,grid)*255.0;\n  return ((vec2(v.r*256.0+v.g,v.b*256.0+v.a)/65535.0)*24.0-12.0)/vec2(128.0,160.0);\n}\nvoid main() {\n  // Invert the intermediate warp with two fixed-point iterations.\n  vec2 p=uv-progress*flow(uv);\n  p=uv-progress*flow(p);\n  vec2 movement=flow(p);\n  // These forms are EXACT identity at their respective endpoints, even when\n  // the iterative inverse estimate has residual error.\n  vec2 fromPoint=uv-progress*movement;\n  vec2 toPoint=uv+(1.0-progress)*movement;\n  float appearance=smoothstep(0.2,0.8,progress);\n  vec4 color;\n  if(appearance<=0.0)color=sharpSample(firstImage,clamp(fromPoint,0.0,1.0));\n  else if(appearance>=1.0)color=sharpSample(secondImage,clamp(toPoint,0.0,1.0));\n  else color=mix(sharpSample(firstImage,clamp(fromPoint,0.0,1.0)),\n                 sharpSample(secondImage,clamp(toPoint,0.0,1.0)),appearance);\n  gl_FragColor=vec4(color.rgb,1.0);\n}", f = class {
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
		if (e.attachShader(n, t(e.VERTEX_SHADER, "attribute vec2 position; varying vec2 uv; void main(){gl_Position=vec4(position,0.,1.);uv=vec2((position.x+1.)*.5,(1.-position.y)*.5);}")), e.attachShader(n, t(e.FRAGMENT_SHADER, d)), e.linkProgram(n), !e.getProgramParameter(n, e.LINK_STATUS)) throw Error("Handoff shader link failed");
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
}, p = null;
function m(e) {
	try {
		if (p && !p.gl.isContextLost()) return;
		let t = p = new f();
		t.render(e, e, /* @__PURE__ */ new Float32Array(714), .25, e.width, e.height), t.gl.finish();
		let n = /* @__PURE__ */ new Float32Array(20480), r = new Float32Array(n.length);
		for (let e = 0; e < 160; e++) for (let t = 0; t < 128; t++) n[e * 128 + t] = 110 + 40 * Math.sin(t * .4) + 30 * Math.sin(e * .53), r[e * 128 + t] = 110 + 40 * Math.sin((t - 2) * .4) + 30 * Math.sin((e - 1) * .53);
		u(n, r), u(r, n);
	} catch {
		p = null;
	}
}
var h = class {
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
		let c = performance.now();
		try {
			let o = u(this.sample(t), this.sample(n));
			if (o.reliable < .15 || o.residual > 800) throw Error("Unreliable frame correspondence");
			this.previous && s(o.xy, this.previous), this.previous = o.xy, p?.gl.isContextLost() && (p = null);
			let c = p ??= new f();
			e.drawImage(c.render(t, n, o.xy, r, i, a), 0, 0, i, a), this.stats = {
				...this.stats,
				mode: "aligned_continuous_warp",
				reliable: o.reliable,
				residual: o.residual,
				peak_displacement: o.peak
			};
		} catch (s) {
			e.drawImage(t, 0, 0, i, a), e.save(), e.globalAlpha = o(r), e.drawImage(n, 0, 0, i, a), e.restore(), this.stats.mode = "unregistered_blend_fallback", this.stats.fallback_frames++, this.stats.last_error = s instanceof Error ? s.message : "render_failed";
		}
		this.stats.frames++, this.stats.peak_ms = Math.max(this.stats.peak_ms, performance.now() - c);
	}
};
//#endregion
export { t as FLOW_H, e as FLOW_W, r as GRID_H, n as GRID_W, h as GeometryHandoff, d as HANDOFF_FRAGMENT, o as appearanceWeight, l as boundFlow, u as matchGeometry, s as smoothFlow, m as warmGeometryHandoff };
