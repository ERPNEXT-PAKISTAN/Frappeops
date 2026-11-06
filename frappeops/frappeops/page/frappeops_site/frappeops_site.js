frappe.pages["frappeops-site"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Site Control"),
		single_column: true,
	});
	const $body = $(wrapper).find(".layout-main-section").length
		? $(wrapper).find(".layout-main-section")
		: page.main;
	page.$fo_body = $body;
	$body.html(`<div class="fo-ctl"><div class="fo-ctl-empty">${__("Loading...")}</div></div>`);
	frappeops_site.render(page);
};

frappe.pages["frappeops-site"].on_page_show = function () {
	const page = frappe.pages["frappeops-site"].page;
	if (page && page.$fo_body) frappeops_site.render(page);
};

const frappeops_site = {
	render(page) {
		const route = frappe.get_route() || [];
		const site_name = route[1] || page._site_name || null;
		page.$fo_body.html(`<div class="fo-ctl"><div class="fo-ctl-empty">${__("Loading...")}</div></div>`);

		frappe.call({
			method: "frappeops.api.site.list_sites",
			callback: (r) => {
				const sites = r.message || [];
				if (!sites.length) {
					page.$fo_body.html(
						`<div class="fo-ctl"><div class="fo-ctl-empty">${__(
							"No sites yet. Open Overview → Scan Server."
						)}</div></div>`
					);
					return;
				}
				const selected =
					site_name && sites.find((s) => s.name === site_name) ? site_name : sites[0].name;
				page._site_name = selected;
				this.load(page, selected, sites);
			},
		});
	},

	load(page, site_name, sites) {
		frappe.call({
			method: "frappeops.api.site.get_site",
			args: { site: site_name },
			callback: (r) => this.paint(page, r.message || {}, sites),
		});
	},

	paint(page, data, sites) {
		const site = data.site || {};
		const $root = $(`<div class="fo-ctl"></div>`);
		const tone = this.tone(site.status);

		$root.append(`
			<div class="fo-ctl-hero">
				<h1>${frappe.utils.escape_html(site.site_name || site.name || "")}</h1>
				<p>${__(
					"Simple site controls — check health, backup, clear cache, install apps. Protected sites block risky actions."
				)}</p>
				<div class="fo-ctl-hero-actions">
					<button class="btn btn-light fo-overview">${__("Overview")}</button>
					<button class="btn btn-ghost fo-install-apps">${__("Install Apps")}</button>
					<button class="btn btn-ghost fo-server">${__("Server")}</button>
					<button class="btn btn-ghost fo-raw">${__("Advanced: open Doc")}</button>
				</div>
			</div>
		`);

		const $toolbar = $(`<div class="fo-ctl-toolbar"></div>`);
		const $select = $(`<select class="form-control" style="max-width:300px"></select>`);
		(sites || []).forEach((s) => {
			$select.append(
				`<option value="${frappe.utils.escape_html(s.name)}" ${s.name === site.name ? "selected" : ""}>${frappe.utils.escape_html(
					s.site_name
				)}${s.is_protected ? " 🔒" : ""}</option>`
			);
		});
		$select.on("change", () => {
			const name = $select.val();
			frappe.set_route("frappeops-site", name);
			page._site_name = name;
			this.load(page, name, sites);
		});
		$toolbar.append($select);
		$toolbar.append(
			$(`<button class="btn btn-default btn-sm">${__("Refresh")}</button>`).on("click", () =>
				this.load(page, site.name, sites)
			)
		);
		$root.append($toolbar);

		const $meta = $(`<div class="fo-ctl-card"><h3>${__("Status")}</h3><div class="fo-ctl-meta"></div></div>`);
		[
			[__("Health"), `<span class="fo-badge ${tone}">${frappe.utils.escape_html(site.status || "Unknown")}</span>`],
			[__("Environment"), site.environment || "—"],
			[__("Protected"), site.is_protected ? __("Yes — risky actions locked") : __("No")],
			[__("Maintenance"), site.maintenance_mode ? __("On") : __("Off")],
			[__("SSL"), site.ssl_state || "—"],
			[__("Domain"), site.primary_domain || "—"],
			[__("Apps"), site.installed_apps || "—"],
			[__("Last check"), site.last_health_check || "—"],
		].forEach(([label, val]) => {
			$meta.find(".fo-ctl-meta").append(`<div><span>${label}</span>${val}</div>`);
		});
		$root.append($meta);

		// Primary easy actions
		const $actions = $(`<div class="fo-ctl-card"><h3>${__("Common actions")}</h3><div class="fo-ctl-actions"></div></div>`);
		const common = [
			{ key: "site.health", label: __("Check Health"), primary: true },
			{ key: "site.backup", label: __("Backup Now") },
			{ key: "site.clear_cache", label: __("Clear Cache"), block_protected: true },
			{ key: "site.maintenance_on", label: __("Maintenance On"), block_protected: true },
			{ key: "site.maintenance_off", label: __("Maintenance Off"), block_protected: true },
		];
		common.forEach((a) => {
			const blocked = site.is_protected && a.block_protected;
			const $btn = $(
				`<button class="btn btn-sm ${a.primary ? "btn-primary" : "btn-default"}">${frappe.utils.escape_html(
					a.label
				)}</button>`
			);
			if (blocked) {
				$btn.attr("disabled", true).attr("title", __("Protected site"));
			} else {
				$btn.on("click", () => this._call(page, a.key, site.name, sites));
			}
			$actions.find(".fo-ctl-actions").append($btn);
		});
		$root.append($actions);

		// Install apps card
		const $install = $(`
			<div class="fo-ctl-card">
				<h3>${__("Install apps on this site")}</h3>
				<div class="fo-ctl-guide" style="margin-bottom:10px">
					${
						site.is_protected
							? __("This site is protected — use Apps & Install on a test site instead.")
							: __(
									"Open the Apps page to pick from the marketplace or apps already on this bench, then install here in one click."
							  )
					}
				</div>
				<div class="fo-ctl-actions"></div>
			</div>
		`);
		$install
			.find(".fo-ctl-actions")
			.append(
				$(
					`<button class="btn btn-primary btn-sm">${__("Open Apps & Install for this site")}</button>`
				).on("click", () => frappe.set_route("frappeops-apps", site.name))
			);
		if (!site.is_protected) {
			$install
				.find(".fo-ctl-actions")
				.append(
					$(`<button class="btn btn-default btn-sm">${__("Quick install from bench…")}</button>`).on(
						"click",
						() => this.quick_install(page, site.name, sites)
					)
				);
		}
		$root.append($install);

		$root.append(this.table_card(__("Recent Backups"), data.backups || [], ["name", "status", "size_mb", "taken_at"]));
		$root.append(this.table_card(__("Recent Jobs"), data.jobs || [], ["name", "operation_type", "status", "creation"]));

		$root.find(".fo-overview").on("click", () => frappe.set_route("frappeops-overview"));
		$root.find(".fo-install-apps").on("click", () => frappe.set_route("frappeops-apps", site.name));
		$root.find(".fo-server").on("click", () => frappe.set_route("frappeops-server", site.server));
		$root.find(".fo-raw").on("click", () => frappe.set_route("Form", "Site", site.name));

		page.$fo_body.empty().append($root);
	},

	quick_install(page, site_name, sites) {
		frappe.call({
			method: "frappeops.api.provision.get_local_apps",
			callback: (r) => {
				const apps = (r.message || []).filter((a) => a !== "frappe");
				if (!apps.length) {
					frappe.msgprint(__("No apps on bench. Open Apps & Install to download from marketplace."));
					return;
				}
				frappe.prompt(
					[
						{
							fieldname: "app",
							fieldtype: "Select",
							label: __("App on this bench"),
							options: apps.join("\n"),
							reqd: 1,
						},
					],
					(values) => this._call(page, "app.install", site_name, sites, { app: values.app }),
					__("Install App on Site")
				);
			},
		});
	},

	table_card(title, rows, fields) {
		const $card = $(`<div class="fo-ctl-card"><h3>${frappe.utils.escape_html(title)}</h3></div>`);
		if (!rows.length) {
			$card.append(`<div class="fo-ctl-sub">${__("None yet")}</div>`);
			return $card;
		}
		rows.slice(0, 8).forEach((row) => {
			$card.append(`
				<div class="fo-ctl-row" style="cursor:default">
					<div class="fo-ctl-title">${frappe.utils.escape_html(String(row[fields[0]] || "—"))}</div>
					<div class="fo-ctl-badges"><span class="fo-badge muted">${frappe.utils.escape_html(
						String(row[fields[1]] || "")
					)}</span></div>
				</div>
			`);
		});
		return $card;
	},

	_call(page, action_key, site_name, sites, params) {
		frappe.call({
			method: "frappeops.services.operations.runner.run_action",
			args: {
				action_key,
				target_type: "site",
				target_name: site_name,
				params: params ? JSON.stringify(params) : null,
			},
			freeze: true,
			freeze_message: __("Working…"),
			callback: (r) => {
				const msg = r.message || {};
				frappe.show_alert({
					message: msg.message || (msg.ok ? __("Done") : __("Failed")),
					indicator: msg.ok ? "green" : "red",
				});
				this.load(page, site_name, sites);
			},
		});
	},

	tone(status) {
		const s = String(status || "").toLowerCase();
		if (["online", "healthy", "success"].includes(s)) return "ok";
		if (["warning", "unknown", "maintenance"].includes(s)) return "warn";
		if (["offline", "critical", "failed"].includes(s)) return "danger";
		return "muted";
	},
};
