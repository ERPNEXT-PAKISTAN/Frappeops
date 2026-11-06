frappe.pages["frappeops-apps"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Apps & Install"),
		single_column: true,
	});
	const $body = $(wrapper).find(".layout-main-section").length
		? $(wrapper).find(".layout-main-section")
		: page.main;
	page.$fo_body = $body;
	$body.html(`<div class="fo-ctl"><div class="fo-ctl-empty">${__("Loading...")}</div></div>`);
	frappeops_apps.render(page);
};

frappe.pages["frappeops-apps"].on_page_show = function () {
	const page = frappe.pages["frappeops-apps"].page;
	if (page && page.$fo_body) frappeops_apps.render(page);
};

const frappeops_apps = {
	render(page) {
		const route = frappe.get_route() || [];
		const site = route[1] || page._site || null;
		page.$fo_body.html(`<div class="fo-ctl"><div class="fo-ctl-empty">${__("Loading apps…")}</div></div>`);
		frappe.call({
			method: "frappeops.api.control.get_apps_hub",
			args: { site },
			callback: (r) => this.paint(page, r.message || {}),
		});
	},

	paint(page, data) {
		const selected = data.selected_site;
		const sites = data.sites || [];
		const $root = $(`<div class="fo-ctl"></div>`);

		$root.append(`
			<div class="fo-ctl-hero">
				<h1>${__("Install an App")}</h1>
				<p>${__(
					"Pick a site, then install an app that is already on this bench — or download from the marketplace first."
				)}</p>
				<div class="fo-ctl-hero-actions">
					<button class="btn btn-light fo-overview">${__("Overview")}</button>
					<button class="btn btn-ghost fo-seed">${__("Refresh Marketplace List")}</button>
				</div>
			</div>
		`);

		$root.append(`
			<div class="fo-ctl-guide">
				<strong>${__("3 easy steps")}</strong>
				<ol class="fo-ctl-steps" style="margin:8px 0 0;padding-left:18px">
					<li>${__("Choose the site (not a locked/protected production site).")}</li>
					<li>${__("If the app is missing from the bench, click Get from Marketplace.")}</li>
					<li>${__("Click Install on this site.")}</li>
				</ol>
			</div>
		`);

		const $toolbar = $(`<div class="fo-ctl-card"><h3>${__("1. Choose site")}</h3><div class="fo-ctl-toolbar"></div></div>`);
		const $select = $(`<select class="form-control" style="max-width:360px"></select>`);
		sites.forEach((s) => {
			const lock = s.is_protected ? ` — ${__("locked")}` : "";
			$select.append(
				`<option value="${frappe.utils.escape_html(s.name)}" ${
					selected && s.name === selected.name ? "selected" : ""
				}>${frappe.utils.escape_html(s.site_name)}${lock}</option>`
			);
		});
		$select.on("change", () => {
			const name = $select.val();
			page._site = name;
			frappe.set_route("frappeops-apps", name);
			this.render(page);
		});
		$toolbar.find(".fo-ctl-toolbar").append($select);
		if (selected) {
			$toolbar.find(".fo-ctl-toolbar").append(
				$(`<button class="btn btn-default btn-sm">${__("Open Site Control")}</button>`).on(
					"click",
					() => frappe.set_route("frappeops-site", selected.name)
				)
			);
		}
		$root.append($toolbar);

		if (!selected) {
			$root.append(`<div class="fo-ctl-empty">${__("No sites found. Scan from Overview first.")}</div>`);
			page.$fo_body.empty().append($root);
			return;
		}

		if (selected.is_protected) {
			$root.append(`
				<div class="fo-ctl-card" style="border-color:#fecaca;background:#fef2f2">
					<h3>${__("This site is protected")}</h3>
					<p class="fo-ctl-sub">${__(
						"FrappeOps will not install apps on protected production sites. Pick another site (e.g. a test site)."
					)}</p>
				</div>
			`);
		}

		const installed = selected.installed_apps || [];
		$root.append(`
			<div class="fo-ctl-card">
				<h3>${__("Installed on {0}", [frappe.utils.escape_html(selected.site_name)])}</h3>
				<div class="fo-ctl-sub">${
					installed.length
						? installed.map((a) => frappe.utils.escape_html(a)).join(", ")
						: __("None listed yet")
				}</div>
			</div>
		`);

		// Ready to install (on disk, not yet on site)
		const ready = (data.on_disk || []).filter(
			(a) => a.app_name !== "frappe" && !a.installed_on_site
		);
		const $ready = $(`<div class="fo-ctl-card"><h3>${__("2. Ready to install (already on this bench)")}</h3></div>`);
		if (!data.can_install) {
			$ready.append(
				`<div class="fo-ctl-empty">${__("Select a non-protected site to enable Install.")}</div>`
			);
		} else if (!ready.length) {
			$ready.append(
				`<div class="fo-ctl-empty">${__(
					"Every app on disk is already installed on this site — or get a new app below."
				)}</div>`
			);
		} else {
			const $grid = $(`<div class="fo-app-grid"></div>`);
			ready.forEach((app) => {
				const $card = $(`
					<div class="fo-app-card">
						<h4>${frappe.utils.escape_html(app.app_name)}</h4>
						<p>${__("Present under apps/ — one click to install on the selected site.")}</p>
						<button class="btn btn-primary btn-sm">${__("Install on this site")}</button>
					</div>
				`);
				$card.find("button").on("click", () => this.install(page, selected.name, app.app_name));
				$grid.append($card);
			});
			$ready.append($grid);
		}
		$root.append($ready);

		// Marketplace
		const $market = $(`<div class="fo-ctl-card"><h3>${__("3. Marketplace / GitHub")}</h3></div>`);
		const catalog = data.catalog || [];
		if (!catalog.length) {
			$market.append(
				`<div class="fo-ctl-empty">${__("No catalog. Click Refresh Marketplace List.")}</div>`
			);
		} else {
			const $grid = $(`<div class="fo-app-grid"></div>`);
			catalog.forEach((item) => {
				let cta = __("Get app");
				let cls = "btn-default";
				if (item.installed_on_site) {
					cta = __("Already installed");
					cls = "btn-default";
				} else if (item.on_disk) {
					cta = __("Install on this site");
					cls = "btn-primary";
				} else {
					cta = __("Download then install");
					cls = "btn-default";
				}
				const $card = $(`
					<div class="fo-app-card">
						<h4>${frappe.utils.escape_html(item.title || item.app_name)}</h4>
						<p>${frappe.utils.escape_html(item.description || item.git_url || "")}</p>
						<div class="fo-ctl-badges" style="justify-content:flex-start;margin-bottom:8px">
							${item.on_disk ? `<span class="fo-badge ok">${__("On bench")}</span>` : `<span class="fo-badge muted">${__("Not downloaded")}</span>`}
							${item.installed_on_site ? `<span class="fo-badge info">${__("On site")}</span>` : ""}
							<span class="fo-badge muted">${frappe.utils.escape_html(item.category || "")}</span>
						</div>
						<button class="btn btn-sm ${cls}" ${item.installed_on_site || !data.can_install ? "disabled" : ""}>${frappe.utils.escape_html(
							cta
						)}</button>
					</div>
				`);
				if (!item.installed_on_site && data.can_install) {
					$card.find("button").on("click", () => {
						if (item.on_disk) {
							this.install(page, selected.name, item.app_name);
						} else {
							this.get_then_install(page, selected.name, item);
						}
					});
				}
				$grid.append($card);
			});
			$market.append($grid);
		}
		$root.append($market);

		// Custom git URL
		const $custom = $(`<div class="fo-ctl-card"><h3>${__("Or paste a GitHub URL")}</h3><div class="fo-ctl-actions"></div></div>`);
		$custom.find(".fo-ctl-actions").append(
			$(`<button class="btn btn-default btn-sm">${__("Get app from HTTPS git URL…")}</button>`).on(
				"click",
				() => this.custom_get(page, selected)
			)
		);
		$root.append($custom);

		$root.find(".fo-overview").on("click", () => frappe.set_route("frappeops-overview"));
		$root.find(".fo-seed").on("click", () => {
			frappe.call({
				method: "frappeops.services.operations.runner.run_action",
				args: { action_key: "app.seed_catalog", target_type: "server" },
				freeze: true,
				callback: () => {
					frappe.show_alert({ message: __("Marketplace refreshed"), indicator: "green" });
					this.render(page);
				},
			});
		});

		page.$fo_body.empty().append($root);
	},

	install(page, site, app) {
		frappe.confirm(
			__("Install <b>{0}</b> on this site?", [frappe.utils.escape_html(app)]),
			() => {
				frappe.call({
					method: "frappeops.services.operations.runner.run_action",
					args: {
						action_key: "app.install",
						target_type: "site",
						target_name: site,
						params: JSON.stringify({ app }),
					},
					freeze: true,
					freeze_message: __("Installing {0}…", [app]),
					callback: (r) => {
						const msg = r.message || {};
						frappe.show_alert({
							message: msg.message || (msg.ok ? __("Installed") : __("Failed")),
							indicator: msg.ok ? "green" : "red",
						});
						this.render(page);
					},
				});
			}
		);
	},

	get_then_install(page, site, item) {
		frappe.confirm(
			__(
				"Download <b>{0}</b> into the bench, then install it on the selected site?",
				[frappe.utils.escape_html(item.title || item.app_name)]
			),
			() => {
				frappe.call({
					method: "frappeops.services.operations.runner.run_action",
					args: {
						action_key: "app.get",
						target_type: "bench",
						params: JSON.stringify({
							catalog_item: item.name,
							branch: item.default_branch,
							confirm: 1,
						}),
					},
					freeze: true,
					freeze_message: __("Downloading {0}…", [item.app_name]),
					callback: (r) => {
						const msg = r.message || {};
						if (!msg.ok && !msg.already_present) {
							frappe.show_alert({ message: msg.message || __("Download failed"), indicator: "red" });
							return;
						}
						this.install(page, site, item.app_name);
					},
				});
			}
		);
	},

	custom_get(page, selected) {
		frappe.prompt(
			[
				{ fieldname: "git_url", fieldtype: "Data", label: __("HTTPS Git URL"), reqd: 1 },
				{ fieldname: "app_name", fieldtype: "Data", label: __("App name (optional)") },
				{ fieldname: "branch", fieldtype: "Data", label: __("Branch"), default: "version-16" },
				{
					fieldname: "also_install",
					fieldtype: "Check",
					label: __("Also install on selected site after download"),
					default: selected && !selected.is_protected ? 1 : 0,
				},
			],
			(values) => {
				frappe.call({
					method: "frappeops.services.operations.runner.run_action",
					args: {
						action_key: "app.get",
						target_type: "bench",
						params: JSON.stringify({
							git_url: values.git_url,
							app_name: values.app_name,
							branch: values.branch,
							confirm: 1,
						}),
					},
					freeze: true,
					freeze_message: __("Downloading…"),
					callback: (r) => {
						const msg = r.message || {};
						if (!msg.ok && !msg.already_present) {
							frappe.show_alert({ message: msg.message || __("Failed"), indicator: "red" });
							return;
						}
						const app = msg.app_name || values.app_name;
						if (values.also_install && app && selected && !selected.is_protected) {
							this.install(page, selected.name, app);
						} else {
							frappe.show_alert({ message: msg.message || __("Downloaded"), indicator: "green" });
							this.render(page);
						}
					},
				});
			},
			__("Get app from Git")
		);
	},
};
