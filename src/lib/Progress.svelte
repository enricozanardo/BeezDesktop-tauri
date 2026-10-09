<script lang="ts">
	let { done = 0, total = 0, label = '' }: { done?: number; total?: number; label?: string } = $props();
	const pct = $derived(total > 0 ? Math.min(100, Math.round((done / total) * 100)) : null);
</script>

<div class="progress-wrap">
	<div class="progress" class:indeterminate={pct === null} role="progressbar" aria-valuenow={pct ?? undefined} aria-valuemin={0} aria-valuemax={100}>
		<div class="bar" style:width={pct === null ? undefined : `${pct}%`}></div>
	</div>
	{#if label}
		<span class="progress-label">{label}{pct !== null ? ` · ${pct}%` : ''}</span>
	{/if}
</div>
