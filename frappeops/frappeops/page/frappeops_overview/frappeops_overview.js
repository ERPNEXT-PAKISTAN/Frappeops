frappe.pages["frappeops-overview"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("FrappeOps"),
		single_column: true,
	});
	const $body = $(wrapper).find(".layout-main-section").length
		? $(wrapper).find(".layout-main-section")
		: page.main;
	page.$fo_body = $body;
	$body.html(`<div class="fo-ctl"><div class="fo-ctl-empty">${__("Loading control panel…")}</div></div>`);
	frappeops_home.render(page);
};

const frappeops_home = {
	render(page) {
		frappe.call({
			method: "frappeops.api.home.get_home",
			callback: (r) => {
				if (!r.message) {
					page.$fo_body.html(
						`<div class="fo-ctl"><div class="fo-ctl-empty">${__("Unable to load.")}</div></div>`
					);
					return;
				}
				this.draw(page, r.message);
			},
		});
	},

	draw(page, data) {
		const ind = data.indicators || {};
		const tree = data.tree || [];
		const alerts = data.alerts || [];
		const agents = data.agents || [];
		const catalog = data.catalog || [];
		const jobs = data.jobs || [];

		const $root = $(`
			<div class="fo-ctl">
				<section class="fo-ctl-hero">
					<h1>${__("FrappeOps")}</h1>
					<p>${__(
						"Control your servers, sites, and apps from simple pages — not confusing forms. Pick a tile below."
					)}</p>
					<div class="fo-ctl-hero-actions">
						<button class="btn btn-light fo-go-sites">${__("Manage Sites")}</button>
						<button class="btn btn-ghost fo-go-apps">${__("Install an App")}</button>
						<button class="btn btn-ghost fo-go-servers">${__("Servers / VPS")}</button>
						<button class="btn btn-ghost fo-scan">${__("Scan This Machine")}</button>
						<button class="btn btn-ghost fo-register-vps">${__("Add Remote VPS")}</button>
						<button class="btn btn-ghost fo-settings">${__("Settings")}</button>
					</div>
				</section>

				<section class="fo-ctl-tiles"></section>

				<div class="fo-ctl-guide">
					<strong>${__("How to use")}</strong> —
					${__(
						"Click a site or server card to open its easy Control page (status + buttons). Use Install an App to put HRMS/CRM/etc on another site."
					)}
				</div>

				<div class="fo-ctl-layout">
					<div>
						<div class="fo-ctl-card"><h3>${__("Your infrastructure")}</h3><div class="fo-tree"></div></div>
					</div>
					<div>
						<div class="fo-ctl-card"><h3>${__("Open alerts")}</h3><div class="fo-alerts"></div></div>
						<div class="fo-ctl-card"><h3>${__("Agents")}</h3><div class="fo-agents"></div></div>
						<div class="fo-ctl-card"><h3>${__("Recent jobs")}</h3><div class="fo-jobs"></div></div>
						<div class="fo-ctl-card"><h3>${__("Marketplace highlights")}</h3><div class="fo-catalog"></div></div>
					</div>
				</div>
			</div>
		`);

		const marketCount = Number(ind.catalog_total != null ? ind.catalog_total : catalog.length) || 0;
		const tiles = [
			{
				k: __("Sites"),
				v: ind.sites_total || 0,
				s: __("Click a site card below"),
				go: () => {
					const first = this.first_site(tree);
					frappe.set_route("frappeops-site", first || "");
				},
			},
			{
				k: __("Servers"),
				v: `${ind.servers_online || 0}/${ind.servers_total || 0}`,
				s: __("Local + remote VPS"),
				go: () => {
					const first = tree[0] && tree[0].name;
					frappe.set_route("frappeops-server", first || "");
				},
			},
			{
				k: __("Marketplace"),
				v: marketCount,
				s: __("{0} apps on bench — install →", [ind.apps_total || 0]),
				go: () => frappe.set_route("frappeops-apps"),
			},
			{
				k: __("Agents"),
				v: `${ind.agents_online || 0}/${ind.agents_total || 0}`,
				s: __("Online / total"),
				go: () => {
					const first = tree[0] && tree[0].name;
					frappe.set_route("frappeops-server", first || "");
				},
			},
		];
		const $tiles = $root.find(".fo-ctl-tiles");
		tiles.forEach((t) => {
			const $el = $(`
				<div class="fo-ctl-tile">
					<div class="k">${frappe.utils.escape_html(t.k)}</div>
					<div class="v">${frappe.utils.escape_html(String(t.v))}</div>
					<div class="s">${frappe.utils.escape_html(t.s)}</div>
				</div>
			`);
			$el.on("click", t.go);
			$tiles.append($el);
		});

		const $tree = $root.find(".fo-tree");
		if (!tree.length) {
			$tree.html(
				`<div class="fo-ctl-empty">${__("Nothing discovered yet.")} <a href="#" class="fo-scan-link">${__(
					"Scan this machine"
				)}</a></div>`
			);
			$tree.find(".fo-scan-link").on("click", (e) => {
				e.preventDefault();
				this.run(page, "server.discover", "server", null);
			});
		} else {
			tree.forEach((server) => $tree.append(this.render_server(page, server)));
		}

		const $alerts = $root.find(".fo-alerts");
		if (!alerts.length) {
			$alerts.append(`<div class="fo-ctl-sub">${__("No open alerts.")}</div>`);
		} else {
			alerts.slice(0, 6).forEach((a) => {
				$alerts.append(`
					<div class="fo-ctl-row" style="cursor:default">
						<div>
							<div class="fo-ctl-title">${frappe.utils.escape_html(a.title || a.name)}</div>
							<div class="fo-ctl-sub">${frappe.utils.escape_html(a.message || "")}</div>
						</div>
						${this.badge(a.severity)}
					</div>
				`);
			});
		}

		const $agents = $root.find(".fo-agents");
		if (!agents.length) {
			$agents.append(`<div class="fo-ctl-sub">${__("No agents. Open a Server page to install/enroll.")}</div>`);
		} else {
			agents.slice(0, 6).forEach((a) => {
				const $row = $(`
					<div class="fo-ctl-row">
						<div>
							<div class="fo-ctl-title">${frappe.utils.escape_html(a.agent_name || a.name)}</div>
							<div class="fo-ctl-sub">${frappe.utils.escape_html(a.status || "")}</div>
						</div>
						${this.badge(a.status)}
					</div>
				`);
				$row.on("click", () => frappe.set_route("frappeops-server", a.server));
				$agents.append($row);
			});
		}

		const $jobs = $root.find(".fo-jobs");
		if (!jobs.length) {
			$jobs.append(`<div class="fo-ctl-sub">${__("No jobs yet.")}</div>`);
		} else {
			jobs.slice(0, 6).forEach((j) => {
				$jobs.append(`
					<div class="fo-ctl-row" style="cursor:default">
						<div>
							<div class="fo-ctl-title">${frappe.utils.escape_html(j.operation_type)}</div>
							<div class="fo-ctl-sub">${frappe.utils.escape_html(j.name)}</div>
						</div>
						${this.badge(j.status)}
					</div>
				`);
			});
		}

		const $catalog = $root.find(".fo-catalog");
		if (!catalog.length) {
			$catalog.append(
				`<div class="fo-ctl-sub">${__("Marketplace empty.")} <a href="#" class="fo-go-apps-link">${__(
					"Open Apps"
				)}</a></div>`
			);
			$catalog.find(".fo-go-apps-link").on("click", (e) => {
				e.preventDefault();
				frappe.set_route("frappeops-apps");
			});
		} else {
			catalog.slice(0, 5).forEach((c) => {
				const $row = $(`
					<div class="fo-ctl-row">
						<div>
							<div class="fo-ctl-title">${frappe.utils.escape_html(c.title || c.app_name)}</div>
							<div class="fo-ctl-sub">${frappe.utils.escape_html(c.category || "")}</div>
						</div>
						<span class="fo-badge info">${__("Install")}</span>
					</div>
				`);
				$row.on("click", () => frappe.set_route("frappeops-apps"));
				$catalog.append($row);
			});
		}

		$root.find(".fo-go-sites").on("click", () =>
			frappe.set_route("frappeops-site", this.first_site(tree) || "")
		);
		$root.find(".fo-go-apps").on("click", () => frappe.set_route("frappeops-apps"));
		$root.find(".fo-go-servers").on("click", () =>
			frappe.set_route("frappeops-server", (tree[0] && tree[0].name) || "")
		);
		$root.find(".fo-scan").on("click", () =>
			this.run(page, "server.discover", "server", tree[0] && tree[0].name)
		);
		$root.find(".fo-register-vps").on("click", () => this.prompt_register_vps(page));
		$root.find(".fo-settings").on("click", () => frappe.set_route("/app/frappeops-settings"));

		page.$fo_body.empty().append($root);
	},

	first_site(tree) {
		for (const s of tree || []) {
			for (const b of s.benches || []) {
				for (const site of b.sites || []) {
					return site.name;
				}
			}
		}
		return null;
	},

	render_server(page, server) {
		const agentLabel = this.agent_label(server.agent_status, server.is_local);
		const $server = $(`
			<div class="fo-ctl-card" style="background:#ecfdf5;border-color:#a7f3d0">
				<div class="fo-ctl-row" style="border:0;padding:0;margin:0;background:transparent">
					<div>
						<div class="fo-ctl-title">${frappe.utils.escape_html(server.server_name || server.name)}</div>
						<div class="fo-ctl-sub">${frappe.utils.escape_html(
							[
								server.hostname,
								server.ip_address,
								server.provider,
								server.is_local ? __("this machine") : __("remote VPS"),
							]
								.filter(Boolean)
								.join(" · ")
						)}</div>
					</div>
					<div class="fo-ctl-badges">
						${this.badge(server.status || __("Unknown"), this.tone(server.status))}
						${this.badge(agentLabel.text, agentLabel.tone)}
					</div>
				</div>
				<div class="fo-ctl-actions" style="margin-top:10px"></div>
				<div class="fo-benches"></div>
			</div>
		`);
		const $actions = $server.find(".fo-ctl-actions");
		$actions.append(
			this.btn(__("Open Server"), () => frappe.set_route("frappeops-server", server.name), true)
		);
		$actions.append(
			this.btn(__("Health"), () => this.run(page, "server.health", "server", server.name))
		);
		if (!server.is_local) {
			$actions.append(
				this.btn(__("Full Status"), () => this.run(page, "server.status", "server", server.name))
			);
			if (String(server.agent_status || "").toLowerCase() !== "online") {
				$actions.append(
					this.btn(__("Enroll Agent"), () =>
						this.run(page, "agent.create_token", "server", server.name)
					)
				);
			}
		}

		(server.benches || []).forEach((bench) => {
			const $bench = $(`
				<div style="margin-top:12px;padding:12px;border-radius:12px;background:#fff;border:1px solid #e5e7eb">
					<div class="fo-ctl-title">${frappe.utils.escape_html(bench.bench_name || bench.name)}</div>
					<div class="fo-ctl-sub">${frappe.utils.escape_html(bench.bench_path || "")}</div>
					<div class="fo-sites"></div>
				</div>
			`);
			(bench.sites || []).forEach((site) => {
				const siteStatus =
					!site.status || String(site.status).toLowerCase() === "unknown"
						? __("Not checked")
						: site.status;
				const $site = $(`
					<div class="fo-ctl-row">
						<div>
							<div class="fo-ctl-title">${frappe.utils.escape_html(site.site_name || site.name)}</div>
							<div class="fo-ctl-sub">${frappe.utils.escape_html(
								[site.environment, site.app_count ? `${site.app_count} apps` : ""]
									.filter(Boolean)
									.join(" · ")
							)}</div>
						</div>
						<div class="fo-ctl-badges">
							${this.badge(siteStatus, this.tone(site.status))}
							${site.is_protected ? this.badge(__("Protected"), "danger") : ""}
							${site.is_control_plane ? this.badge(__("Control"), "info") : ""}
						</div>
					</div>
				`);
				$site.on("click", () => frappe.set_route("frappeops-site", site.name));
				$bench.find(".fo-sites").append($site);
			});
			if (!(bench.sites || []).length) {
				$bench.append(
					`<div class="fo-ctl-sub" style="margin-top:8px">${__(
						"No sites on this server yet (remote needs agent)."
					)}</div>`
				);
			}
			$server.find(".fo-benches").append($bench);
		});

		if (!(server.benches || []).length) {
			$server.find(".fo-benches").append(
				`<div class="fo-ctl-sub" style="margin-top:10px">${__(
					"No bench linked yet. For a remote VPS, enroll the agent then Scan."
				)}</div>`
			);
		}

		return $server;
	},

	agent_label(agent_status, is_local) {
		const s = String(agent_status || "").toLowerCase();
		if (s === "online") return { text: __("Agent OK"), tone: "ok" };
		if (s === "enrolled") return { text: __("Agent enrolled"), tone: "info" };
		if (s === "pending") return { text: __("Agent waiting"), tone: "warn" };
		if (s === "not installed" || !s) {
			return {
				text: is_local ? __("Agent missing") : __("Needs agent"),
				tone: "warn",
			};
		}
		if (s === "offline") return { text: __("Agent offline"), tone: "danger" };
		return { text: agent_status, tone: this.tone(agent_status) };
	},

	btn(label, fn, primary) {
		const $b = $(
			`<button class="btn btn-sm ${primary ? "btn-primary" : "btn-default"}">${frappe.utils.escape_html(
				label
			)}</button>`
		);
		$b.on("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			fn();
		});
		return $b;
	},

	badge(text, tone) {
		return `<span class="fo-badge ${tone || this.tone(text)}">${frappe.utils.escape_html(
			String(text || "—")
		)}</span>`;
	},

	tone(status) {
		const s = String(status || "").toLowerCase();
		if (["online", "healthy", "success", "enrolled"].includes(s)) return "ok";
		if (["warning", "pending", "unknown", "not installed", "queued", "running"].includes(s)) return "warn";
		if (["offline", "critical", "failed", "revoked"].includes(s)) return "danger";
		return "muted";
	},

	prompt_register_vps(page) {
		frappe.prompt(
			[
				{ fieldname: "server_name", fieldtype: "Data", label: __("Name"), reqd: 1, default: "contabo-vps" },
				{ fieldname: "ip_address", fieldtype: "Data", label: __("Public IP"), reqd: 1 },
				{ fieldname: "provider", fieldtype: "Data", label: __("Provider"), default: "Contabo" },
				{
					fieldname: "create_token",
					fieldtype: "Check",
					label: __("Create enroll token + install script"),
					default: 1,
				},
			],
			(values) =>
				this.run(page, "server.register_vps", "server", null, {
					server_name: values.server_name,
					ip_address: values.ip_address,
					provider: values.provider,
					create_token: values.create_token ? 1 : 0,
				}),
			__("Add Remote VPS")
		);
	},

	run(page, action_key, target_type, target_name, params) {
		frappe.call({
			method: "frappeops.services.operations.runner.run_action",
			args: {
				action_key,
				target_type,
				target_name,
				params: params ? JSON.stringify(params) : null,
			},
			freeze: true,
			freeze_message: __("Working…"),
			callback: (r) => {
				const msg = r.message || {};
				const enrollTok =
					msg.enrollment_token || (msg.enrollment && msg.enrollment.enrollment_token);
				const script = msg.script || msg.install_script;
				if (msg.ok && (enrollTok || script)) {
					const bits = [frappe.utils.escape_html(msg.message || __("Done"))];
					if (enrollTok) {
						bits.push(
							`<b>${__("Token (copy now)")}:</b> <code>${frappe.utils.escape_html(enrollTok)}</code>`
						);
					}
					if (script) {
						bits.push(
							`<pre style="max-height:240px;overflow:auto;white-space:pre-wrap">${frappe.utils.escape_html(
								script
							)}</pre>`
						);
					}
					frappe.msgprint({ title: __("Copy now"), message: bits.join("<br><br>"), indicator: "green" });
				} else if (msg.ok && msg.status && typeof msg.status === "object") {
					frappe.msgprint({
						title: __("Status"),
						message: `<pre style="max-height:320px;overflow:auto">${frappe.utils.escape_html(
							JSON.stringify(msg.status, null, 2)
						)}</pre>`,
						indicator: "blue",
					});
				} else {
					frappe.show_alert({
						message: msg.message || (msg.ok ? __("Done") : __("Failed")),
						indicator: msg.ok ? "green" : "red",
					});
				}
				this.render(page);
			},
		});
	},
};
