<script lang="ts" module>
	import { feature } from 'topojson-client';
	import land110 from 'world-atlas/land-110m.json';

	type Ring = [number, number][];
	type Poly = { rings: Ring[]; box: [number, number, number, number] };

	export type Region = {
		label: string;
		lon: [number, number];
		lat: [number, number];
		step: number;
		/** Horizontal scale (cos of the central latitude) so regional maps are not stretched. */
		kx: number;
	};

	export const REGIONS: Record<string, Region> = {
		europe: { label: 'Europe', lon: [-12, 40], lat: [34, 71], step: 0.5, kx: Math.cos((52 * Math.PI) / 180) },
		world: { label: 'World', lon: [-180, 180], lat: [-56, 76], step: 2.5, kx: 1 }
	};

	let polyCache: Poly[] | null = null;

	function polygons(): Poly[] {
		if (polyCache) return polyCache;
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
		polyCache = out;
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

	const dotCache = new Map<Region, [number, number][]>();

	export function landDots(r: Region): [number, number][] {
		const cached = dotCache.get(r);
		if (cached) return cached;
		const polys = polygons();
		const dots: [number, number][] = [];
		const lonStep = r.step / r.kx;
		for (let lat = r.lat[1] - r.step / 2; lat > r.lat[0]; lat -= r.step) {
			for (let lon = r.lon[0] + lonStep / 2; lon < r.lon[1]; lon += lonStep) {
				if (onLand(lon, lat, polys)) dots.push(project(r, lon, lat));
			}
		}
		dotCache.set(r, dots);
		return dots;
	}

	export function project(r: Region, lon: number, lat: number): [number, number] {
		return [(lon - r.lon[0]) * r.kx, r.lat[1] - lat];
	}

	export function contains(r: Region, lon: number, lat: number): boolean {
		return lon >= r.lon[0] && lon <= r.lon[1] && lat >= r.lat[0] && lat <= r.lat[1];
	}
</script>

<script lang="ts">
	type Pin = { id: string; lon: number; lat: number; type: string; title: string };
	let {
		pins,
		selected = $bindable(''),
		region = $bindable('europe'),
		onselect = () => {}
	}: { pins: Pin[]; selected?: string; region?: string; onselect?: (id: string) => void } = $props();

	const r = $derived(REGIONS[region] || REGIONS.europe);
	const width = $derived((r.lon[1] - r.lon[0]) * r.kx);
	const height = $derived(r.lat[1] - r.lat[0]);
	const dots = $derived(landDots(r));
	const visible = $derived(pins.filter((p) => contains(r, p.lon, p.lat)));
	const outside = $derived(pins.length - visible.length);

	const placed = $derived.by(() => {
		const groups = new Map<string, Pin[]>();
		for (const p of visible) {
			const key = `${p.lon.toFixed(1)},${p.lat.toFixed(1)}`;
			groups.set(key, [...(groups.get(key) || []), p]);
		}
		const out: (Pin & { x: number; y: number })[] = [];
		for (const group of groups.values()) {
			group.forEach((p, i) => {
				const [x, y] = project(r, p.lon, p.lat);
				const spread = group.length > 1 ? r.step * 1.05 : 0;
				const a = (i / group.length) * Math.PI * 2;
				out.push({ ...p, x: x + spread * Math.cos(a), y: y + spread * Math.sin(a) });
			});
		}
		return out;
	});
</script>

<div class="map-regions">
	{#each Object.entries(REGIONS) as [key, reg] (key)}
		<button class={region === key ? 'primary' : 'ghost'} onclick={() => (region = key)}>{reg.label}</button>
	{/each}
	{#if outside > 0}<span class="meta">{outside} node{outside > 1 ? 's' : ''} outside this view</span>{/if}
</div>
<svg class="world-map" viewBox="0 0 {width} {height}" role="img" aria-label="Node locations on a map of {r.label}">
	{#each dots as [x, y]}
		<circle class="land" cx={x} cy={y} r={r.step * 0.3} />
	{/each}
	{#each placed as p (p.id)}
		<circle
			class="node-dot {p.type}"
			class:selected={p.id === selected}
			cx={p.x}
			cy={p.y}
			r={r.step * (p.id === selected ? 0.95 : 0.7)}
			style:stroke-width={r.step * (p.id === selected ? 0.55 : 0.24)}
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
