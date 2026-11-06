frappe.pages["frappeops-server"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Server Control"),
		single_column: true,
	});
	const $body = $(wrapper).find(".layout-main-section").length
		? $(wrapper).find(".layout-main-section")
		: page.main;
	page.$fo_body = $body;
	$body.html(`<div class="fo-ctl"><div class="fo-ctl-empty">${__("Loading...")}</div></div>`);
	frappeops_server.render(page);
};

frappe.pages["frappeops-server"].on_page_show = function () {
	const page = frappe.pages["frappeops-server"].page;
	if (page && page.$fo_body) frappeops_server.render(page);
};

const frappeops_server = {
	render(page) {
		const route = frappe.get_route() || [];
		const wanted = route[1] || page._server || null;
		page.$fo_body.html(`<div class="fo-ctl"><div class="fo-ctl-empty">${__("Loading server...")}</div></div>`);

		frappe.call({
			method: "frappeops.api.control.list_servers",
			callback: (r) => {
				const servers = r.message || [];
				if (!servers.length) {
					page.$fo_body.html(
						`<div class="fo-ctl"><div class="fo-ctl-empty">${__(
							"No servers yet. Open Overview → Register VPS or Scan."
						)}</div></div>`
					);
					return;
				}
				const selected =
					wanted && servers.find((s) => s.name === wanted) ? wanted : servers[0].name;
				page._server = selected;
				this.load(page, selected, servers);
			},
		});
	},

	load(page, server, servers) {
		frappe.call({
			method: "frappeops.api.control.get_server",
			args: { server },
			callback: (r) => this.paint(page, r.message || {}, servers),
		});
	},

	paint(page, data, servers) {
		const s = data.server || {};
		const status = data.status || {};
		const $root = $(`<div class="fo-ctl"></div>`);

		$root.append(`
			<div class="fo-ctl-hero">
				<h1>${frappe.utils.escape_html(s.server_name || s.name || __("Server"))}</h1>
				<p>${__(
					"Easy server view — health, agent, sites. Use actions below instead of opening the raw Server form."
				)}</p>
				<div class="fo-ctl-hero-actions">
					<button class="btn btn-light fo-overview">${__("Overview")}</button>
					<button class="btn btn-ghost fo-apps">${__("Install Apps")}</button>
					<button class="btn btn-ghost fo-raw">${__("Advanced: open Doc")}</button>
				</div>
			</div>
		`);

		const $toolbar = $(`<div class="fo-ctl-toolbar"></div>`);
		const $select = $(`<select class="form-control" style="max-width:300px"></select>`);
		(servers || []).forEach((row) => {
			$select.append(
				`<option value="${frappe.utils.escape_html(row.name)}" ${
					row.name === s.name ? "selected" : ""
				}>${frappe.utils.escape_html(row.server_name)}${row.is_local ? " (local)" : ""}</option>`
			);
		});
		$select.on("change", () => {
			const name = $select.val();
			frappe.set_route("frappeops-server", name);
			page._server = name;
			this.load(page, name, servers);
		});
		$toolbar.append($select);
		$toolbar.append(
			$(`<button class="btn btn-default btn-sm">${__("Refresh")}</button>`).on("click", () =>
				this.load(page, s.name, servers)
			)
		);
		$root.append($toolbar);

		const $meta = $(`<div class="fo-ctl-card"><h3>${__("Status")}</h3><div class="fo-ctl-meta"></div></div>`);
		const rows = [
			[__("Status"), this.badge(s.status)],
			[__("Agent"), this.badge(s.agent_status || "—")],
			[__("Host"), s.hostname || "—"],
			[__("IP"), s.ip_address || "—"],
			[__("Provider"), s.provider || (s.is_local ? __("Local") : "—")],
			[__("Disk"), s.disk_used_percent != null ? `${s.disk_used_percent}%` : "—"],
			[__("RAM"), s.ram_gb ? `${s.ram_gb} GB` : "—"],
			[__("CPU cores"), s.cpu_cores || "—"],
			[__("Last heartbeat"), s.last_heartbeat || "—"],
		];
		rows.forEach(([label, val]) => {
			$meta.find(".fo-ctl-meta").append(`<div><span>${label}</span>${val}</div>`);
		});
		$root.append($meta);

		const facts = (status && status.facts) || {};
		if ((facts.sites || []).length || (facts.apps || []).length) {
			$root.append(`
				<div class="fo-ctl-card">
					<h3>${__("Agent snapshot")}</h3>
					<div class="fo-ctl-sub">${__("Sites on this machine")}: ${(facts.sites || [])
						.map((x) => frappe.utils.escape_html(x))
						.join(", ") || "—"}</div>
					<div class="fo-ctl-sub" style="margin-top:6px">${__("Apps on disk")}: ${(facts.apps || [])
						.slice(0, 20)
						.map((x) => frappe.utils.escape_html(x))
						.join(", ") || "—"}</div>
				</div>
			`);
		}

		const $actions = $(`<div class="fo-ctl-card"><h3>${__("Actions")}</h3><div class="fo-ctl-actions"></div></div>`);
		const simple = [
			{ key: "server.health", label: __("Check Health"), primary: true },
			{ key: "server.status", label: __("Full Status") },
			{ key: "server.discover", label: __("Scan / Discover") },
			{ key: "monitor.poll", label: __("Poll Alerts") },
		];
		if (s.is_local) {
			simple.push({ key: "agent.install_local", label: __("Install Local Agent") });
			simple.push({ key: "agent.start_listener", label: __("Start Listener") });
		} else {
			simple.push({ key: "agent.create_token", label: __("New Enroll Token") });
			simple.push({ key: "agent.install_script", label: __("Install Script") });
		}
		simple.forEach((a) => {
			const $btn = $(
				`<button class="btn btn-sm ${a.primary ? "btn-primary" : "btn-default"}">${frappe.utils.escape_html(
					a.label
				)}</button>`
			);
			$btn.on("click", () => this.run(page, a.key, s.name, servers));
			$actions.find(".fo-ctl-actions").append($btn);
		});
		$root.append($actions);

		const $sites = $(`<div class="fo-ctl-card"><h3>${__("Sites on this server")}</h3></div>`);
		if (!(data.sites || []).length) {
			$sites.append(`<div class="fo-ctl-empty">${__("No sites linked yet")}</div>`);
		} else {
			(data.sites || []).forEach((site) => {
				const $row = $(`
					<div class="fo-ctl-row">
						<div>
							<div class="fo-ctl-title">${frappe.utils.escape_html(site.site_name)}</div>
							<div class="fo-ctl-sub">${frappe.utils.escape_html(site.environment || "")}</div>
						</div>
						<div class="fo-ctl-badges">${this.badge(site.status)}${
							site.is_protected ? this.badge(__("Protected"), "danger") : ""
						}</div>
					</div>
				`);
				$row.on("click", () => frappe.set_route("frappeops-site", site.name));
				$sites.append($row);
			});
		}
		$root.append($sites);

		const $agents = $(`<div class="fo-ctl-card"><h3>${__("Agents")}</h3></div>`);
		if (!(data.agents || []).length) {
			$agents.append(
				`<div class="fo-ctl-empty">${__(
					"No agent yet. Local: Install Local Agent. Remote: New Enroll Token."
				)}</div>`
			);
		} else {
			(data.agents || []).forEach((a) => {
				$agents.append(`
					<div class="fo-ctl-row" style="cursor:default">
						<div>
							<div class="fo-ctl-title">${frappe.utils.escape_html(a.agent_name || a.name)}</div>
							<div class="fo-ctl-sub">${frappe.utils.escape_html(a.listen_url || __("no listen URL"))}</div>
						</div>
						<div class="fo-ctl-badges">${this.badge(a.status)}</div>
					</div>
				`);
			});
		}
		$root.append($agents);

		$root.find(".fo-overview").on("click", () => frappe.set_route("frappeops-overview"));
		$root.find(".fo-apps").on("click", () => frappe.set_route("frappeops-apps"));
		$root.find(".fo-raw").on("click", () => frappe.set_route("Form", "Server", s.name));

		page.$fo_body.empty().append($root);
	},

	run(page, action_key, server, servers) {
		frappe.call({
			method: "frappeops.services.operations.runner.run_action",
			args: {
				action_key,
				target_type: "server",
				target_name: server,
			},
			freeze: true,
			freeze_message: __("Running…"),
			callback: (r) => {
				const msg = r.message || {};
				const enrollTok =
					msg.enrollment_token || (msg.enrollment && msg.enrollment.enrollment_token);
				const script = msg.script || msg.install_script;
				if (msg.ok && (enrollTok || script || (msg.status && typeof msg.status === "object"))) {
					const bits = [frappe.utils.escape_html(msg.message || __("Done"))];
					if (enrollTok) {
						bits.push(
							`<b>${__("Token (copy now)")}:</b> <code>${frappe.utils.escape_html(enrollTok)}</code>`
						);
					}
					if (script) {
						bits.push(
							`<pre style="max-height:260px;overflow:auto;white-space:pre-wrap">${frappe.utils.escape_html(
								script
							)}</pre>`
						);
					}
					if (msg.status && typeof msg.status === "object") {
						bits.push(
							`<pre style="max-height:260px;overflow:auto">${frappe.utils.escape_html(
								JSON.stringify(msg.status, null, 2)
							)}</pre>`
						);
					}
					frappe.msgprint({ title: __("Result"), message: bits.join("<br><br>"), indicator: "green" });
				} else {
					frappe.show_alert({
						message: msg.message || (msg.ok ? __("Done") : __("Failed")),
						indicator: msg.ok ? "green" : "red",
					});
				}
				this.load(page, server, servers);
			},
		});
	},

	badge(text, tone) {
		const t = tone || this.tone(text);
		return `<span class="fo-badge ${t}">${frappe.utils.escape_html(String(text || "—"))}</span>`;
	},

	tone(status) {
		const s = String(status || "").toLowerCase();
		if (["online", "healthy", "success", "enrolled"].includes(s)) return "ok";
		if (["warning", "pending", "unknown", "not installed"].includes(s)) return "warn";
		if (["offline", "critical", "failed", "revoked"].includes(s)) return "danger";
		return "muted";
	},
};
