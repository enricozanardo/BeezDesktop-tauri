<script lang="ts" module>
	import { feature } from 'topojson-client';
	import land110 from 'world-atlas/land-110m.json';

	type Ring = [number, number][];
	type Poly = { rings: Ring[]; box: [number, number, number, number] };

	const W = 360;
	const H = 150;
	const LAT_TOP = 80;
	const LAT_BOTTOM = -60;
	const STEP = 2.5;

	function polygons(): Poly[] {
		const topo = land110 as unknown as Parameters<typeof feature>[0];
		const geo = feature(topo, (topo as unknown as { objects: { land: never } }).objects.land) as unknown as {
			features: { geometry: { type: string; coordinates: unknown } }[];
		};
		const out: Poly[] = [];
		for (const f of geo.features) {
			const g = f.geometry;
			const polys = (g.type === 'Polygon' ? [g.coordinates] : g.coordinates) as Ring[][];
			for (const rings of polys) {
				const xs = rings[0].map((p) => p[0]);
				const ys = rings[0].map((p) => p[1]);
				out.push({ rings, box: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] });
			}
		}
		return out;
	}

	function inRing(lon: number, lat: number, ring: Ring): boolean {
		let inside = false;
		for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
			const [xi, yi] = ring[i];
			const [xj, yj] = ring[j];
			if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
		}
		return inside;
	}

	function onLand(lon: number, lat: number, polys: Poly[]): boolean {
		for (const p of polys) {
			const [x0, y0, x1, y1] = p.box;
			if (lon < x0 || lon > x1 || lat < y0 || lat > y1) continue;
			if (inRing(lon, lat, p.rings[0]) && !p.rings.slice(1).some((h) => inRing(lon, lat, h))) return true;
		}
		return false;
	}

	let dotCache: [number, number][] | null = null;

	export function landDots(): [number, number][] {
		if (dotCache) return dotCache;
		const polys = polygons();
		const dots: [number, number][] = [];
		for (let lat = LAT_TOP; lat >= LAT_BOTTOM; lat -= STEP) {
			for (let lon = -180 + STEP / 2; lon < 180; lon += STEP) {
				if (onLand(lon, lat, polys)) dots.push(project(lon, lat));
			}
		}
		dotCache = dots;
		return dots;
	}

	export function project(lon: number, lat: number): [number, number] {
		return [((lon + 180) / 360) * W, ((LAT_TOP - lat) / (LAT_TOP - LAT_BOTTOM)) * H];
	}
</script>

<script lang="ts">
	type Pin = { id: string; lon: number; lat: number; type: string; title: string };
	let {
		pins,
		selected = $bindable(''),
		onselect = () => {}
	}: { pins: Pin[]; selected?: string; onselect?: (id: string) => void } = $props();

	const dots = landDots();

	const placed = $derived.by(() => {
		const groups = new Map<string, Pin[]>();
		for (const p of pins) {
			const key = `${p.lon.toFixed(1)},${p.lat.toFixed(1)}`;
			groups.set(key, [...(groups.get(key) || []), p]);
		}
		const out: (Pin & { x: number; y: number })[] = [];
		for (const group of groups.values()) {
			group.forEach((p, i) => {
				const [x, y] = project(p.lon, p.lat);
				const r = group.length > 1 ? 2.6 : 0;
				const a = (i / group.length) * Math.PI * 2;
				out.push({ ...p, x: x + r * Math.cos(a), y: y + r * Math.sin(a) });
			});
		}
		return out;
	});
</script>

<svg class="world-map" viewBox="0 0 {W} {H}" role="img" aria-label="Node locations on a world map">
	{#each dots as [x, y]}
		<circle class="land" cx={x} cy={y} r="0.75" />
	{/each}
	{#each placed as p (p.id)}
		<circle
			class="node-dot {p.type}"
			class:selected={p.id === selected}
			cx={p.x}
			cy={p.y}
			r={p.id === selected ? 2.4 : 1.7}
			role="button"
			tabindex="0"
			aria-label={p.title}
			onclick={() => {
				selected = p.id;
				onselect(p.id);
			}}
			onkeydown={(e) => e.key === 'Enter' && ((selected = p.id), onselect(p.id))}
		>
			<title>{p.title}</title>
		</circle>
	{/each}
</svg>
