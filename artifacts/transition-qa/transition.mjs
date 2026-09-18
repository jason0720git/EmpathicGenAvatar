//#region apps/web/src/faceTransitionMesh.ts
var e = (e) => {
	let t = Math.max(0, Math.min(1, e));
	return t * t * (3 - 2 * t);
};
function t(t, n) {
	return e((t - .12) / .2) * e((.88 - t) / .2) * e((n - .02) / .18) * e((.9 - n) / .3);
}
function n(e, n, r, i, a) {
	let o = t(e, n) * a;
	return [e + r * o, n + i * o];
}
function r(e, t, n, r, i, a) {
	let o = n[1][0] - n[0][0], s = n[1][1] - n[0][1], c = n[2][0] - n[0][0], l = n[2][1] - n[0][1], u = o * l - c * s, d = r[1][0] - r[0][0], f = r[1][1] - r[0][1], p = r[2][0] - r[0][0], m = r[2][1] - r[0][1], h = (d * l - p * s) / u, g = (f * l - m * s) / u, _ = (p * o - d * c) / u, v = (m * o - f * c) / u;
	e.save(), e.beginPath(), e.moveTo(...r[0]), e.lineTo(...r[1]), e.lineTo(...r[2]), e.closePath(), e.clip(), e.transform(h, g, _, v, r[0][0] - h * n[0][0] - _ * n[0][1], r[0][1] - g * n[0][0] - v * n[0][1]), e.drawImage(t, 0, 0, i, a), e.restore();
}
function i(e, t, i, a, o) {
	if (!o || !i && !a) return;
	let s = e.canvas.width, c = e.canvas.height, l = [
		0,
		.18,
		.32,
		.5,
		.68,
		.82,
		1
	], u = [
		0,
		.08,
		.2,
		.4,
		.6,
		.78,
		1
	];
	for (let d = 0; d < u.length - 1; d++) for (let f = 0; f < l.length - 1; f++) {
		let p = [
			[l[f], u[d]],
			[l[f + 1], u[d]],
			[l[f + 1], u[d + 1]],
			[l[f], u[d + 1]]
		], m = p.map(([e, t]) => [e * s, t * c]), h = p.map(([e, t]) => {
			let r = n(e, t, i, a, o);
			return [r[0] * s, r[1] * c];
		});
		for (let n of [[
			0,
			1,
			2
		], [
			0,
			2,
			3
		]]) r(e, t, n.map((e) => m[e]), n.map((e) => h[e]), s, c);
	}
}
//#endregion
//#region apps/web/src/avatarTransition.ts
var a = 480, o = 160, s = 480;
function c(e) {
	let t = Math.max(0, Math.min(1, e));
	return t * t * t * (10 + t * (-15 + 6 * t));
}
function l(e, t, n, r) {
	let i = (i, a) => {
		let o = 0, s = 0;
		for (let c = Math.ceil(r * .2); c < r * .55; c += 2) for (let l = Math.ceil(n * .25); l < n * .75; l += 2) {
			let u = l - i, d = c - a, f = Math.floor(u), p = Math.floor(d);
			if (f < 0 || p < 0 || f + 1 >= n || p + 1 >= r) continue;
			let m = u - f, h = d - p, g = t[p * n + f] * (1 - m) * (1 - h) + t[p * n + f + 1] * m * (1 - h) + t[(p + 1) * n + f] * (1 - m) * h + t[(p + 1) * n + f + 1] * m * h;
			o += Math.min(2500, (e[c * n + l] - g) ** 2), s++;
		}
		return o / Math.max(1, s);
	}, a = 0, o = 0, s = i(0, 0), c = s;
	for (let e = -3; e <= 3; e++) for (let t = -3; t <= 3; t++) {
		let n = i(t, e);
		n < s && (s = n, a = t, o = e);
	}
	let l = a, u = o;
	for (let e = u - .5; e <= u + .5; e += .25) for (let t = l - .5; t <= l + .5; t += .25) {
		let n = i(t, e);
		n < s && (s = n, a = t, o = e);
	}
	let d = c > 1 && s < c * .9 && s < 600 && Math.abs(a) <= 3.5 && Math.abs(o) <= 3.5;
	return {
		dx: d ? a / n : 0,
		dy: d ? o / r : 0,
		angle: 0,
		scale: 1,
		improvement: c > 0 ? 1 - s / c : 0,
		accepted: d
	};
}
function u(e) {
	let t = document.createElement("canvas");
	t.width = 96, t.height = 120;
	let n = t.getContext("2d", { willReadFrequently: !0 });
	n.drawImage(e, 0, 0, 96, 120);
	let r = n.getImageData(0, 0, 96, 120).data, i = /* @__PURE__ */ new Float32Array(11520);
	for (let e = 0; e < i.length; e++) i[e] = r[e * 4] * .299 + r[e * 4 + 1] * .587 + r[e * 4 + 2] * .114;
	return i;
}
function d(e, t, n) {
	let r = {
		dx: 0,
		dy: 0,
		accepted: !1,
		improvement: 0
	};
	try {
		n && (r = l(u(e), u(n), 96, 120));
	} catch {}
	return (Math.abs(r.dx) > .02 || Math.abs(r.dy) > .02) && (r = {
		...r,
		dx: 0,
		dy: 0,
		accepted: !1
	}), {
		from: e,
		...r,
		angle: 0,
		scale: 1,
		started: t,
		mixMs: 480,
		faceLocal: !0
	};
}
function f(e, t, n, r, i, a = !0) {
	try {
		let o = document.createElement("canvas");
		return o.width = n, o.height = r, o.getContext("2d").drawImage(e, 0, 0, n, r), {
			from: o,
			...a ? l(u(o), u(t), 96, 120) : {
				dx: 0,
				dy: 0,
				angle: 0,
				scale: 1,
				accepted: !1,
				improvement: 0
			},
			started: i
		};
	} catch {
		return null;
	}
}
function p(e, t, n, r) {
	let a = e.canvas.width, o = e.canvas.height;
	if (e.drawImage(t, 0, 0, a, o), !n) return;
	let s = Math.max(0, r - n.started), l = 1 - c(s / 480);
	if (l <= 0) return;
	n.faceLocal ? i(e, t, n.dx, n.dy, l) : (n.dx || n.dy) && (e.save(), e.translate(n.dx * a * l, n.dy * o * l), e.drawImage(t, 0, 0, a, o), e.restore());
	let u = 1 - c(s / (n.mixMs ?? 160));
	u > 0 && (e.save(), e.globalAlpha = u, e.drawImage(n.from, 0, 0, a, o), e.restore());
}
//#endregion
export { s as ENTRY_MIX_MS, o as MIX_MS, a as TRANSITION_MS, d as beginIdleEntryTransition, f as beginTransition, p as drawTransition, c as ease, l as estimateShift };
