import { invoke } from '@tauri-apps/api/core';

export async function appVersion(): Promise<string> {
	try {
		return await invoke<string>('app_version');
	} catch {
		return '0.1.23-web';
	}
}

export async function sidecarCall(method: string, params: Record<string, unknown> = {}) {
	const payload = JSON.stringify({ method, params });
	try {
		const raw = await invoke<string>('sidecar_call', { payload });
		return JSON.parse(raw) as Record<string, unknown>;
	} catch (err) {
		return { ok: false, error: String(err) };
	}
}
