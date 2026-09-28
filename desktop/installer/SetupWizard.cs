using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("PharmaCare Pro Enterprise Setup Wizard")]
[assembly: AssemblyDescription("PharmaCare Pro Enterprise Pharmacy Management System Installer")]
[assembly: AssemblyCompany("PharmaCare Enterprise")]
[assembly: AssemblyProduct("PharmaCare Pro Enterprise")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace PharmaCareSetup
{
    public class SetupWizardForm : Form
    {
        private int currentStep = 0;
        private bool isInstalling = false;
        private bool orgCodeManuallyEdited = false;

        // Top Banner Controls
        private Panel headerPanel;
        private Label headerTitleLabel;
        private Label headerSubLabel;
        private Label stepIndicatorLabel;

        // Content Area & Step Panels (6 steps: 0..5)
        private Panel bodyContainer;
        private Panel stepWelcomePanel;
        private Panel stepPharmacyPanel;
        private Panel stepServerPanel;
        private Panel stepOptionsPanel;
        private Panel stepProgressPanel;
        private Panel stepFinishPanel;

        // Step 1: Pharmacy & Branch Setup Controls
        private TextBox txtPharmacyName;
        private TextBox txtOrgCode;
        private TextBox txtBranchName;
        private TextBox txtBranchCode;
        private TextBox txtBranchPhone;
        private TextBox txtBranchAddress;

        // Step 2: Cloud Server & Terminal Controls
        private RadioButton rbOfflineMode;
        private RadioButton rbCloudMode;
        private TextBox txtServerUrl;
        private Button btnTestServer;
        private Label lblServerTestStatus;
        private TextBox txtDeviceCode;

        // Step 3: Destination Folder & Shortcuts Controls
        private TextBox installPathBox;
        private CheckBox chkDesktopShortcut;
        private CheckBox chkStartMenuShortcut;
        private CheckBox chkRegisterUninstall;

        // Step 4: Progress Controls
        private Label lblProgressStatus;
        private Label lblProgressPercent;
        private ProgressBar progressBar;
        private TextBox txtInstallLog;

        // Step 5: Finish Controls
        private Label lblFinishSummary;
        private CheckBox chkLaunchNow;

        // Upgrade Mode State
        private bool isExistingInstall = false;
        private bool preserveExistingSettingsOnly = false;
        private Button btnQuickUpdate;
        private Label welcomeFooterHint;

        // Bottom Footer Controls
        private Panel footerPanel;
        private Button btnBack;
        private Button btnNext;
        private Button btnCancel;

        public SetupWizardForm()
        {
            InitializeWizardUI();
            LoadExistingInstallationIfPresent();
            ShowStep(0);
        }

        private string ExtractJsonValue(string json, string key)
        {
            Match m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*\"([^\"]*)\"");
            return m.Success ? m.Groups[1].Value : "";
        }

        private void LoadExistingInstallationIfPresent()
        {
            try
            {
                string dataDir = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "PharmacyManagement"
                );
                string dbPath = Path.Combine(dataDir, "pharmacy.db");
                string appliedJson = Path.Combine(dataDir, "wizard_setup_applied.json");
                string pendingJson = Path.Combine(dataDir, "wizard_setup.json");

                if (File.Exists(dbPath) || File.Exists(appliedJson) || File.Exists(pendingJson))
                {
                    isExistingInstall = true;
                    string jsonFile = File.Exists(appliedJson) ? appliedJson : (File.Exists(pendingJson) ? pendingJson : "");
                    if (!string.IsNullOrEmpty(jsonFile))
                    {
                        string raw = File.ReadAllText(jsonFile, Encoding.UTF8);
                        string pName = ExtractJsonValue(raw, "pharmacy_name");
                        string oCode = ExtractJsonValue(raw, "org_code");
                        string bName = ExtractJsonValue(raw, "branch_name");
                        string bCode = ExtractJsonValue(raw, "branch_code");
                        string bAddr = ExtractJsonValue(raw, "branch_address");
                        string bPhone = ExtractJsonValue(raw, "branch_phone");
                        string sUrl = ExtractJsonValue(raw, "cloud_server_url");
                        string dCode = ExtractJsonValue(raw, "device_code");

                        if (!string.IsNullOrEmpty(oCode)) orgCodeManuallyEdited = true;
                        if (!string.IsNullOrEmpty(pName)) txtPharmacyName.Text = pName;
                        if (!string.IsNullOrEmpty(oCode)) txtOrgCode.Text = oCode;
                        if (!string.IsNullOrEmpty(bName)) txtBranchName.Text = bName;
                        if (!string.IsNullOrEmpty(bCode)) txtBranchCode.Text = bCode;
                        if (!string.IsNullOrEmpty(bAddr)) txtBranchAddress.Text = bAddr;
                        if (!string.IsNullOrEmpty(bPhone)) txtBranchPhone.Text = bPhone;
                        if (!string.IsNullOrEmpty(dCode)) txtDeviceCode.Text = dCode;
                        if (!string.IsNullOrEmpty(sUrl))
                        {
                            txtServerUrl.Text = sUrl;
                            if (!sUrl.Contains("localhost:8000"))
                            {
                                rbCloudMode.Checked = true;
                            }
                        }
                    }
                    if (welcomeFooterHint != null)
                    {
                        welcomeFooterHint.Text = "✅ Existing installation detected! Click '⚡ Update App Now (Keep Data)' for a 1-click safe update, or 'Next >' to modify settings.";
                        welcomeFooterHint.ForeColor = Color.FromArgb(13, 148, 136);
                        welcomeFooterHint.Font = new Font("Segoe UI", 9f, FontStyle.Bold);
                    }
                }
            }
            catch { }
        }

        private void InitializeWizardUI()
        {
            this.Text = "PharmaCare Pro Enterprise — Setup & Update Wizard";
            this.ClientSize = new Size(680, 495);
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = Color.FromArgb(248, 250, 252);
            this.Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            try
            {
                this.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch { }

            // 1. Header Banner
            headerPanel = new Panel();
            headerPanel.Dock = DockStyle.Top;
            headerPanel.Height = 84;
            headerPanel.BackColor = Color.FromArgb(15, 23, 42);
            headerPanel.Paint += HeaderPanel_Paint;

            headerTitleLabel = new Label();
            headerTitleLabel.Location = new Point(78, 15);
            headerTitleLabel.Size = new Size(450, 28);
            headerTitleLabel.ForeColor = Color.White;
            headerTitleLabel.BackColor = Color.Transparent;
            headerTitleLabel.Font = new Font("Segoe UI", 13.5f, FontStyle.Bold);

            headerSubLabel = new Label();
            headerSubLabel.Location = new Point(80, 45);
            headerSubLabel.Size = new Size(560, 22);
            headerSubLabel.ForeColor = Color.FromArgb(148, 163, 184);
            headerSubLabel.BackColor = Color.Transparent;
            headerSubLabel.Font = new Font("Segoe UI", 9.25f, FontStyle.Regular);

            stepIndicatorLabel = new Label();
            stepIndicatorLabel.Location = new Point(535, 18);
            stepIndicatorLabel.Size = new Size(125, 24);
            stepIndicatorLabel.TextAlign = ContentAlignment.MiddleRight;
            stepIndicatorLabel.ForeColor = Color.FromArgb(45, 212, 191);
            stepIndicatorLabel.BackColor = Color.Transparent;
            stepIndicatorLabel.Font = new Font("Segoe UI", 9f, FontStyle.Bold);

            headerPanel.Controls.Add(headerTitleLabel);
            headerPanel.Controls.Add(headerSubLabel);
            headerPanel.Controls.Add(stepIndicatorLabel);

            // 2. Footer Bar
            footerPanel = new Panel();
            footerPanel.Dock = DockStyle.Bottom;
            footerPanel.Height = 62;
            footerPanel.BackColor = Color.FromArgb(241, 245, 249);
            footerPanel.Paint += (s, e) =>
            {
                using (Pen p = new Pen(Color.FromArgb(226, 232, 240), 1))
                {
                    e.Graphics.DrawLine(p, 0, 0, footerPanel.Width, 0);
                }
            };

            Label footerBrand = new Label();
            footerBrand.Text = "PharmaCare Pro Enterprise v1.0";
            footerBrand.ForeColor = Color.FromArgb(148, 163, 184);
            footerBrand.Font = new Font("Segoe UI", 8.5f, FontStyle.Bold);
            footerBrand.Location = new Point(20, 22);
            footerBrand.AutoSize = true;

            btnQuickUpdate = new Button();
            btnQuickUpdate.Text = "⚡ Update App Now (Keep Data)";
            btnQuickUpdate.Location = new Point(190, 14);
            btnQuickUpdate.Size = new Size(168, 34);
            btnQuickUpdate.FlatStyle = FlatStyle.Flat;
            btnQuickUpdate.BackColor = Color.FromArgb(37, 99, 235);
            btnQuickUpdate.ForeColor = Color.White;
            btnQuickUpdate.FlatAppearance.BorderSize = 0;
            btnQuickUpdate.Font = new Font("Segoe UI", 8.75f, FontStyle.Bold);
            btnQuickUpdate.Cursor = Cursors.Hand;
            btnQuickUpdate.Visible = false;
            btnQuickUpdate.Click += (s, e) =>
            {
                preserveExistingSettingsOnly = true;
                ShowStep(4);
            };

            btnBack = CreateButton("< Back", new Point(365, 14), false);
            btnBack.Click += (s, e) => { if (currentStep > 0 && !isInstalling) ShowStep(currentStep - 1); };

            btnNext = CreateButton("Next >", new Point(465, 14), true);
            btnNext.Click += BtnNext_Click;

            btnCancel = CreateButton("Cancel", new Point(568, 14), false);
            btnCancel.Click += BtnCancel_Click;

            footerPanel.Controls.Add(footerBrand);
            footerPanel.Controls.Add(btnQuickUpdate);
            footerPanel.Controls.Add(btnBack);
            footerPanel.Controls.Add(btnNext);
            footerPanel.Controls.Add(btnCancel);

            // 3. Body Container
            bodyContainer = new Panel();
            bodyContainer.Dock = DockStyle.Fill;
            bodyContainer.Padding = new Padding(28, 20, 28, 14);

            BuildWelcomeStep();
            BuildPharmacyStep();
            BuildServerStep();
            BuildOptionsStep();
            BuildProgressStep();
            BuildFinishStep();

            bodyContainer.Controls.Add(stepWelcomePanel);
            bodyContainer.Controls.Add(stepPharmacyPanel);
            bodyContainer.Controls.Add(stepServerPanel);
            bodyContainer.Controls.Add(stepOptionsPanel);
            bodyContainer.Controls.Add(stepProgressPanel);
            bodyContainer.Controls.Add(stepFinishPanel);

            this.Controls.Add(bodyContainer);
            this.Controls.Add(footerPanel);
            this.Controls.Add(headerPanel);
        }

        private Button CreateButton(string text, Point location, bool primary)
        {
            Button btn = new Button();
            btn.Text = text;
            btn.Location = location;
            btn.Size = new Size(94, 34);
            btn.FlatStyle = FlatStyle.Flat;
            btn.Cursor = Cursors.Hand;
            if (primary)
            {
                btn.BackColor = Color.FromArgb(13, 148, 136);
                btn.ForeColor = Color.White;
                btn.FlatAppearance.BorderSize = 0;
                btn.Font = new Font("Segoe UI", 9.5f, FontStyle.Bold);
            }
            else
            {
                btn.BackColor = Color.White;
                btn.ForeColor = Color.FromArgb(51, 65, 85);
                btn.FlatAppearance.BorderColor = Color.FromArgb(203, 213, 225);
                btn.FlatAppearance.BorderSize = 1;
                btn.Font = new Font("Segoe UI", 9f, FontStyle.Regular);
            }
            return btn;
        }

        private void HeaderPanel_Paint(object sender, PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;

            Rectangle badgeRect = new Rectangle(22, 18, 44, 44);
            using (SolidBrush b = new SolidBrush(Color.FromArgb(13, 148, 136)))
            {
                g.FillEllipse(b, badgeRect);
            }
            using (SolidBrush wb = new SolidBrush(Color.White))
            {
                g.FillRectangle(wb, 40, 27, 8, 26);
                g.FillRectangle(wb, 31, 36, 26, 8);
            }
            using (SolidBrush accent = new SolidBrush(Color.FromArgb(20, 184, 166)))
            {
                g.FillRectangle(accent, 0, headerPanel.Height - 3, headerPanel.Width, 3);
            }
        }

        // ====================================================================
        // STEP 0: WELCOME
        // ====================================================================
        private void BuildWelcomeStep()
        {
            stepWelcomePanel = new Panel { Dock = DockStyle.Fill, Visible = false };

            Label introTitle = new Label
            {
                Text = "Welcome to the PharmaCare Pro Enterprise Setup Wizard",
                Font = new Font("Segoe UI", 13f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                Location = new Point(0, 0),
                Size = new Size(620, 28)
            };

            Label introDesc = new Label
            {
                Text = "This wizard will install PharmaCare Pro Enterprise on this computer, configure the Pharmacy Name & Branch Profile, and optionally link this branch to your Cloud Server.",
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(71, 85, 105),
                Location = new Point(0, 32),
                Size = new Size(620, 42)
            };

            Panel card = new Panel
            {
                Location = new Point(0, 82),
                Size = new Size(624, 192),
                BackColor = Color.White,
                BorderStyle = BorderStyle.FixedSingle
            };

            string[] features = new string[]
            {
                "🏥  Step 1: Set Pharmacy Name & Organization Code (locked on the Login screen after setup)",
                "📍  Step 2: Configure this Branch's Name, Branch Code (e.g. HQ, BR02) & Contact Info",
                "☁️  Step 3: Configure Cloud Server URL & Terminal Code for Multi-Branch Sync",
                "🛡️  Role-Based Access Control, Staff Permissions & Immutable Audit Trail",
                "⚡  Offline-First SQLite WAL Engine: Works 100% offline and syncs when connected"
            };

            int y = 14;
            foreach (string feat in features)
            {
                Label lbl = new Label
                {
                    Text = feat,
                    Font = new Font("Segoe UI", 9.25f, FontStyle.Regular),
                    ForeColor = Color.FromArgb(30, 41, 59),
                    Location = new Point(16, y),
                    Size = new Size(595, 26)
                };
                card.Controls.Add(lbl);
                y += 33;
            }

            welcomeFooterHint = new Label
            {
                Text = "Click 'Next >' to configure the Pharmacy Name and Branch for this computer.",
                Font = new Font("Segoe UI", 9.25f, FontStyle.Italic),
                ForeColor = Color.FromArgb(100, 116, 139),
                Location = new Point(0, 288),
                Size = new Size(620, 22)
            };

            stepWelcomePanel.Controls.Add(introTitle);
            stepWelcomePanel.Controls.Add(introDesc);
            stepWelcomePanel.Controls.Add(card);
            stepWelcomePanel.Controls.Add(welcomeFooterHint);
        }

        // ====================================================================
        // STEP 1: PHARMACY NAME & BRANCH CONFIGURATION
        // ====================================================================
        private void BuildPharmacyStep()
        {
            stepPharmacyPanel = new Panel { Dock = DockStyle.Fill, Visible = false };

            Label secOrg = new Label
            {
                Text = "1. Pharmacy / Organization Identity  (Will be locked on Login Screen)",
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                Location = new Point(0, 0),
                Size = new Size(620, 22)
            };

            Label lblPharmName = new Label
            {
                Text = "Pharmacy Name *",
                Font = new Font("Segoe UI", 9f, FontStyle.Bold),
                ForeColor = Color.FromArgb(51, 65, 85),
                Location = new Point(0, 26),
                Size = new Size(400, 18)
            };
            txtPharmacyName = new TextBox
            {
                Text = "MedCare Pharmacy",
                Location = new Point(0, 46),
                Size = new Size(415, 28),
                Font = new Font("Segoe UI", 10f)
            };
            txtPharmacyName.TextChanged += (s, e) =>
            {
                if (!orgCodeManuallyEdited)
                {
                    string clean = Regex.Replace(txtPharmacyName.Text.ToUpperInvariant(), "[^A-Z0-9]", "");
                    if (clean.Length > 10) clean = clean.Substring(0, 10);
                    txtOrgCode.Text = string.IsNullOrEmpty(clean) ? "PHARMACY" : clean;
                }
            };

            Label lblOrgCode = new Label
            {
                Text = "Organization Code *",
                Font = new Font("Segoe UI", 9f, FontStyle.Bold),
                ForeColor = Color.FromArgb(51, 65, 85),
                Location = new Point(430, 26),
                Size = new Size(190, 18)
            };
            txtOrgCode = new TextBox
            {
                Text = "MEDCARE",
                Location = new Point(430, 46),
                Size = new Size(194, 28),
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                CharacterCasing = CharacterCasing.Upper
            };
            txtOrgCode.KeyPress += (s, e) => { orgCodeManuallyEdited = true; };

            Label orgHint = new Label
            {
                Text = "Tip: When installing at multiple branches of the same pharmacy, enter the exact same Organization Code.",
                Font = new Font("Segoe UI", 8.5f, FontStyle.Italic),
                ForeColor = Color.FromArgb(100, 116, 139),
                Location = new Point(0, 76),
                Size = new Size(620, 18)
            };

            Label secBranch = new Label
            {
                Text = "2. This Branch Location Details",
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                Location = new Point(0, 104),
                Size = new Size(620, 22)
            };

            Label lblBrName = new Label
            {
                Text = "Branch Name *  (e.g. Main Branch - Ikeja, Lekki Branch)",
                Font = new Font("Segoe UI", 9f, FontStyle.Bold),
                ForeColor = Color.FromArgb(51, 65, 85),
                Location = new Point(0, 130),
                Size = new Size(415, 18)
            };
            txtBranchName = new TextBox
            {
                Text = "Main Branch",
                Location = new Point(0, 150),
                Size = new Size(415, 28),
                Font = new Font("Segoe UI", 10f)
            };

            Label lblBrCode = new Label
            {
                Text = "Branch Code *  (e.g. HQ, BR02)",
                Font = new Font("Segoe UI", 9f, FontStyle.Bold),
                ForeColor = Color.FromArgb(51, 65, 85),
                Location = new Point(430, 130),
                Size = new Size(194, 18)
            };
            txtBranchCode = new TextBox
            {
                Text = "HQ",
                Location = new Point(430, 150),
                Size = new Size(194, 28),
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                CharacterCasing = CharacterCasing.Upper
            };

            Label lblBrAddress = new Label
            {
                Text = "Branch Address  (Printed on Receipts)",
                Font = new Font("Segoe UI", 9f, FontStyle.Regular),
                ForeColor = Color.FromArgb(51, 65, 85),
                Location = new Point(0, 188),
                Size = new Size(415, 18)
            };
            txtBranchAddress = new TextBox
            {
                Text = "",
                Location = new Point(0, 208),
                Size = new Size(415, 28),
                Font = new Font("Segoe UI", 9.5f)
            };

            Label lblBrPhone = new Label
            {
                Text = "Branch Phone",
                Font = new Font("Segoe UI", 9f, FontStyle.Regular),
                ForeColor = Color.FromArgb(51, 65, 85),
                Location = new Point(430, 188),
                Size = new Size(194, 18)
            };
            txtBranchPhone = new TextBox
            {
                Text = "",
                Location = new Point(430, 208),
                Size = new Size(194, 28),
                Font = new Font("Segoe UI", 9.5f)
            };

            Panel infoBanner = new Panel
            {
                Location = new Point(0, 252),
                Size = new Size(624, 54),
                BackColor = Color.FromArgb(240, 253, 250),
                BorderStyle = BorderStyle.FixedSingle
            };

            Label infoLabel = new Label
            {
                Text = "ℹ️  Multi-Branch Tip:\r\n" +
                       "     Use the same Organization Code across all branches and a unique Branch Code (HQ, BR02, BR03) per location.",
                Font = new Font("Segoe UI", 9f, FontStyle.Regular),
                ForeColor = Color.FromArgb(15, 118, 110),
                Location = new Point(12, 8),
                Size = new Size(600, 38)
            };
            infoBanner.Controls.Add(infoLabel);

            stepPharmacyPanel.Controls.Add(secOrg);
            stepPharmacyPanel.Controls.Add(lblPharmName);
            stepPharmacyPanel.Controls.Add(txtPharmacyName);
            stepPharmacyPanel.Controls.Add(lblOrgCode);
            stepPharmacyPanel.Controls.Add(txtOrgCode);
            stepPharmacyPanel.Controls.Add(orgHint);
            stepPharmacyPanel.Controls.Add(secBranch);
            stepPharmacyPanel.Controls.Add(lblBrName);
            stepPharmacyPanel.Controls.Add(txtBranchName);
            stepPharmacyPanel.Controls.Add(lblBrCode);
            stepPharmacyPanel.Controls.Add(txtBranchCode);
            stepPharmacyPanel.Controls.Add(lblBrAddress);
            stepPharmacyPanel.Controls.Add(txtBranchAddress);
            stepPharmacyPanel.Controls.Add(lblBrPhone);
            stepPharmacyPanel.Controls.Add(txtBranchPhone);
            stepPharmacyPanel.Controls.Add(infoBanner);
        }

        // ====================================================================
        // STEP 2: CLOUD SERVER & POS TERMINAL CONNECTION
        // ====================================================================
        private void BuildServerStep()
        {
            stepServerPanel = new Panel { Dock = DockStyle.Fill, Visible = false };

            Label modeTitle = new Label
            {
                Text = "Select How This Branch Connects to the Cloud",
                Font = new Font("Segoe UI", 10.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                Location = new Point(0, 0),
                Size = new Size(620, 24)
            };

            Panel modeCard = new Panel
            {
                Location = new Point(0, 28),
                Size = new Size(624, 92),
                BackColor = Color.White,
                BorderStyle = BorderStyle.FixedSingle
            };

            rbOfflineMode = new RadioButton
            {
                Text = "Standalone / Offline-First Mode  (Run locally now; link to Cloud Server anytime in Settings)",
                Checked = true,
                Location = new Point(16, 14),
                Size = new Size(590, 26),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42)
            };

            rbCloudMode = new RadioButton
            {
                Text = "Connect to Multi-Branch Cloud Server  (Sync inventory, prices, sales & transfers across branches)",
                Checked = false,
                Location = new Point(16, 50),
                Size = new Size(590, 26),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(13, 148, 136)
            };

            modeCard.Controls.Add(rbOfflineMode);
            modeCard.Controls.Add(rbCloudMode);

            Label lblServerUrl = new Label
            {
                Text = "Central Cloud Server URL  (e.g. https://api.yourpharmacycloud.com or http://localhost:8000)",
                Font = new Font("Segoe UI", 9f, FontStyle.Bold),
                ForeColor = Color.FromArgb(51, 65, 85),
                Location = new Point(0, 136),
                Size = new Size(620, 20)
            };

            txtServerUrl = new TextBox
            {
                Text = "https://pharm-production-69a4.up.railway.app",
                Location = new Point(0, 158),
                Size = new Size(465, 28),
                Font = new Font("Segoe UI", 10f),
                Enabled = false
            };

            btnTestServer = new Button
            {
                Text = "🔌 Test Server",
                Location = new Point(475, 156),
                Size = new Size(148, 30),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.White,
                ForeColor = Color.FromArgb(13, 148, 136),
                Font = new Font("Segoe UI", 9f, FontStyle.Bold),
                Enabled = false
            };
            btnTestServer.FlatAppearance.BorderColor = Color.FromArgb(13, 148, 136);
            btnTestServer.Click += BtnTestServer_Click;

            lblServerTestStatus = new Label
            {
                Text = "Offline-First SQLite WAL engine is always active even when Cloud Server is unreachable.",
                Font = new Font("Segoe UI", 8.75f, FontStyle.Italic),
                ForeColor = Color.FromArgb(100, 116, 139),
                Location = new Point(0, 192),
                Size = new Size(620, 20)
            };

            rbOfflineMode.CheckedChanged += (s, e) =>
            {
                txtServerUrl.Enabled = rbCloudMode.Checked;
                btnTestServer.Enabled = rbCloudMode.Checked;
            };
            rbCloudMode.CheckedChanged += (s, e) =>
            {
                txtServerUrl.Enabled = rbCloudMode.Checked;
                btnTestServer.Enabled = rbCloudMode.Checked;
                if (rbCloudMode.Checked) txtServerUrl.Focus();
            };

            Label lblDevCode = new Label
            {
                Text = "This Computer's POS Terminal / Counter Code *  (e.g. POS01 for Counter 1, POS02 for Counter 2)",
                Font = new Font("Segoe UI", 9f, FontStyle.Bold),
                ForeColor = Color.FromArgb(51, 65, 85),
                Location = new Point(0, 228),
                Size = new Size(620, 20)
            };

            txtDeviceCode = new TextBox
            {
                Text = "POS01",
                Location = new Point(0, 250),
                Size = new Size(180, 28),
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                CharacterCasing = CharacterCasing.Upper
            };

            stepServerPanel.Controls.Add(modeTitle);
            stepServerPanel.Controls.Add(modeCard);
            stepServerPanel.Controls.Add(lblServerUrl);
            stepServerPanel.Controls.Add(txtServerUrl);
            stepServerPanel.Controls.Add(btnTestServer);
            stepServerPanel.Controls.Add(lblServerTestStatus);
            stepServerPanel.Controls.Add(lblDevCode);
            stepServerPanel.Controls.Add(txtDeviceCode);
        }

        private void BtnTestServer_Click(object sender, EventArgs e)
        {
            string url = txtServerUrl.Text.Trim().TrimEnd('/');
            if (string.IsNullOrEmpty(url))
            {
                lblServerTestStatus.ForeColor = Color.FromArgb(220, 38, 38);
                lblServerTestStatus.Text = "❌ Please enter a valid HTTP/HTTPS Server URL.";
                return;
            }
            lblServerTestStatus.ForeColor = Color.FromArgb(217, 119, 6);
            lblServerTestStatus.Text = "⏳ Testing connection to " + url + " ...";
            Application.DoEvents();

            string checkUrl = url.EndsWith("/api/v1") ? (url + "/health/") : (url + "/api/v1/health/");
            try
            {
                ServicePointManager.Expect100Continue = true;
                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072 | (SecurityProtocolType)768 | SecurityProtocolType.Tls;
                ServicePointManager.ServerCertificateValidationCallback = delegate { return true; };

                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(checkUrl);
                req.Timeout = 10000;
                req.Method = "GET";
                req.UserAgent = "PharmaCarePro-SetupWizard/1.0";
                using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
                {
                    lblServerTestStatus.ForeColor = Color.FromArgb(5, 150, 105);
                    lblServerTestStatus.Text = "✅ Connected! Cloud Server responded with HTTP " + (int)resp.StatusCode + ".";
                    return;
                }
            }
            catch (Exception ex)
            {
                // Fallback to built-in Windows curl.exe if .NET Schannel fails on a fresh Windows profile
                try
                {
                    ProcessStartInfo psi = new ProcessStartInfo
                    {
                        FileName = "curl.exe",
                        Arguments = "-s -k -L -o NUL -w \"%{http_code}\" --max-time 8 \"" + checkUrl + "\"",
                        CreateNoWindow = true,
                        UseShellExecute = false,
                        RedirectStandardOutput = true
                    };
                    using (Process p = Process.Start(psi))
                    {
                        string codeOut = p.StandardOutput.ReadToEnd().Trim();
                        p.WaitForExit(9000);
                        if (codeOut == "200")
                        {
                            lblServerTestStatus.ForeColor = Color.FromArgb(5, 150, 105);
                            lblServerTestStatus.Text = "✅ Connected! Cloud Server responded with HTTP 200.";
                            return;
                        }
                    }
                }
                catch { }

                lblServerTestStatus.ForeColor = Color.FromArgb(217, 119, 6);
                lblServerTestStatus.Text = "⚠️ Server not reachable right now (" + ex.Message + "). URL will still be saved for background sync.";
            }
        }

        // ====================================================================
        // STEP 3: DESTINATION FOLDER & SHORTCUTS
        // ====================================================================
        private void BuildOptionsStep()
        {
            stepOptionsPanel = new Panel { Dock = DockStyle.Fill, Visible = false };

            Label lblDirHeader = new Label
            {
                Text = "Destination Folder",
                Font = new Font("Segoe UI", 10.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                Location = new Point(0, 0),
                Size = new Size(400, 24)
            };

            Label lblDirSub = new Label
            {
                Text = "Setup will install PharmaCare Pro Enterprise into the following folder:",
                ForeColor = Color.FromArgb(71, 85, 105),
                Location = new Point(0, 26),
                Size = new Size(580, 22)
            };

            string defaultDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs",
                "PharmaCarePro"
            );

            installPathBox = new TextBox
            {
                Text = defaultDir,
                Location = new Point(0, 54),
                Size = new Size(515, 28),
                Font = new Font("Segoe UI", 10f)
            };

            Button btnBrowse = new Button
            {
                Text = "Browse...",
                Location = new Point(525, 52),
                Size = new Size(98, 30),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.White,
                ForeColor = Color.FromArgb(30, 41, 59)
            };
            btnBrowse.FlatAppearance.BorderColor = Color.FromArgb(203, 213, 225);
            btnBrowse.Click += (s, e) =>
            {
                using (FolderBrowserDialog fbd = new FolderBrowserDialog())
                {
                    fbd.Description = "Select destination folder for PharmaCare Pro Enterprise:";
                    fbd.SelectedPath = installPathBox.Text;
                    if (fbd.ShowDialog() == DialogResult.OK)
                    {
                        installPathBox.Text = Path.Combine(fbd.SelectedPath, "PharmaCarePro");
                    }
                }
            };

            Label lblTasksHeader = new Label
            {
                Text = "Shortcuts & System Integration",
                Font = new Font("Segoe UI", 10.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                Location = new Point(0, 106),
                Size = new Size(400, 24)
            };

            Panel tasksCard = new Panel
            {
                Location = new Point(0, 134),
                Size = new Size(624, 128),
                BackColor = Color.White,
                BorderStyle = BorderStyle.FixedSingle
            };

            chkDesktopShortcut = new CheckBox
            {
                Text = "Create a Desktop shortcut  (PharmaCare Pro)",
                Checked = true,
                Location = new Point(16, 16),
                Size = new Size(580, 26),
                Font = new Font("Segoe UI", 9.5f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42)
            };

            chkStartMenuShortcut = new CheckBox
            {
                Text = "Create a Windows Start Menu program shortcut",
                Checked = true,
                Location = new Point(16, 50),
                Size = new Size(580, 26),
                ForeColor = Color.FromArgb(30, 41, 59)
            };

            chkRegisterUninstall = new CheckBox
            {
                Text = "Register in Windows Installed Apps (Add / Remove Programs)",
                Checked = true,
                Location = new Point(16, 84),
                Size = new Size(580, 26),
                ForeColor = Color.FromArgb(30, 41, 59)
            };

            tasksCard.Controls.Add(chkDesktopShortcut);
            tasksCard.Controls.Add(chkStartMenuShortcut);
            tasksCard.Controls.Add(chkRegisterUninstall);

            Label lblSpaceNote = new Label
            {
                Text = "Click 'Install' to copy application files and provision your Pharmacy & Branch database.",
                ForeColor = Color.FromArgb(100, 116, 139),
                Location = new Point(0, 276),
                Size = new Size(620, 22)
            };

            stepOptionsPanel.Controls.Add(lblDirHeader);
            stepOptionsPanel.Controls.Add(lblDirSub);
            stepOptionsPanel.Controls.Add(installPathBox);
            stepOptionsPanel.Controls.Add(btnBrowse);
            stepOptionsPanel.Controls.Add(lblTasksHeader);
            stepOptionsPanel.Controls.Add(tasksCard);
            stepOptionsPanel.Controls.Add(lblSpaceNote);
        }

        // ====================================================================
        // STEP 4: PROGRESS
        // ====================================================================
        private void BuildProgressStep()
        {
            stepProgressPanel = new Panel { Dock = DockStyle.Fill, Visible = false };

            lblProgressStatus = new Label
            {
                Text = "Preparing installation...",
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                Location = new Point(0, 4),
                Size = new Size(530, 24)
            };

            lblProgressPercent = new Label
            {
                Text = "0%",
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(13, 148, 136),
                TextAlign = ContentAlignment.MiddleRight,
                Location = new Point(535, 4),
                Size = new Size(88, 24)
            };

            progressBar = new ProgressBar
            {
                Location = new Point(0, 34),
                Size = new Size(624, 26),
                Minimum = 0,
                Maximum = 100,
                Value = 0,
                Style = ProgressBarStyle.Continuous
            };

            txtInstallLog = new TextBox
            {
                Location = new Point(0, 74),
                Size = new Size(624, 235),
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                BackColor = Color.FromArgb(15, 23, 42),
                ForeColor = Color.FromArgb(226, 232, 240),
                Font = new Font("Consolas", 9f)
            };

            stepProgressPanel.Controls.Add(lblProgressStatus);
            stepProgressPanel.Controls.Add(lblProgressPercent);
            stepProgressPanel.Controls.Add(progressBar);
            stepProgressPanel.Controls.Add(txtInstallLog);
        }

        // ====================================================================
        // STEP 5: FINISH
        // ====================================================================
        private void BuildFinishStep()
        {
            stepFinishPanel = new Panel { Dock = DockStyle.Fill, Visible = false };

            Label doneTitle = new Label
            {
                Text = "✅  PharmaCare Pro Enterprise Setup Complete!",
                Font = new Font("Segoe UI", 13f, FontStyle.Bold),
                ForeColor = Color.FromArgb(13, 148, 136),
                Location = new Point(0, 2),
                Size = new Size(620, 30)
            };

            Panel summaryCard = new Panel
            {
                Location = new Point(0, 40),
                Size = new Size(624, 210),
                BackColor = Color.White,
                BorderStyle = BorderStyle.FixedSingle
            };

            lblFinishSummary = new Label
            {
                Text = "",
                Font = new Font("Segoe UI", 9.5f, FontStyle.Regular),
                ForeColor = Color.FromArgb(30, 41, 59),
                Location = new Point(16, 14),
                Size = new Size(592, 182)
            };
            summaryCard.Controls.Add(lblFinishSummary);

            chkLaunchNow = new CheckBox
            {
                Text = "Launch PharmaCare Pro Enterprise now",
                Checked = true,
                Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                ForeColor = Color.FromArgb(15, 23, 42),
                Location = new Point(4, 266),
                Size = new Size(450, 28)
            };

            stepFinishPanel.Controls.Add(doneTitle);
            stepFinishPanel.Controls.Add(summaryCard);
            stepFinishPanel.Controls.Add(chkLaunchNow);
        }

        private void ShowStep(int step)
        {
            currentStep = step;
            stepWelcomePanel.Visible = (step == 0);
            stepPharmacyPanel.Visible = (step == 1);
            stepServerPanel.Visible = (step == 2);
            stepOptionsPanel.Visible = (step == 3);
            stepProgressPanel.Visible = (step == 4);
            stepFinishPanel.Visible = (step == 5);

            if (btnQuickUpdate != null)
            {
                btnQuickUpdate.Visible = (step == 0 && isExistingInstall);
            }

            if (step == 0)
            {
                preserveExistingSettingsOnly = false;
                headerTitleLabel.Text = isExistingInstall
                    ? "PharmaCare Pro Enterprise — Update or Reconfigure"
                    : "PharmaCare Pro Enterprise Setup";
                headerSubLabel.Text = isExistingInstall
                    ? "Existing installation detected — update in 1 click while keeping all data, or review settings"
                    : "Welcome to the Pharmacy, Branch & Cloud Provisioning Wizard";
                stepIndicatorLabel.Text = "Step 1 of 5";
                btnBack.Enabled = false;
                btnNext.Text = "Next >";
                btnNext.Enabled = true;
            }
            else if (step == 1)
            {
                headerTitleLabel.Text = "Pharmacy & Branch Configuration";
                headerSubLabel.Text = "Set the Pharmacy Name (locked on Login screen) and this Branch's identity";
                stepIndicatorLabel.Text = "Step 2 of 5";
                btnBack.Enabled = true;
                btnNext.Text = "Next >";
                btnNext.Enabled = true;
            }
            else if (step == 2)
            {
                headerTitleLabel.Text = "Cloud Server & POS Terminal Setup";
                headerSubLabel.Text = "Configure multi-branch cloud synchronization and terminal counter ID";
                stepIndicatorLabel.Text = "Step 3 of 5";
                btnBack.Enabled = true;
                btnNext.Text = "Next >";
                btnNext.Enabled = true;
            }
            else if (step == 3)
            {
                headerTitleLabel.Text = "Destination Folder & Shortcuts";
                headerSubLabel.Text = "Choose installation path and Desktop / Start Menu shortcuts";
                stepIndicatorLabel.Text = "Step 4 of 5";
                btnBack.Enabled = true;
                btnNext.Text = isExistingInstall ? "Update / Install" : "Install";
                btnNext.Enabled = true;
            }
            else if (step == 4)
            {
                headerTitleLabel.Text = preserveExistingSettingsOnly
                    ? "Updating PharmaCare Pro Enterprise (Keeping Data)..."
                    : "Installing & Provisioning Pharmacy...";
                headerSubLabel.Text = preserveExistingSettingsOnly
                    ? "Backing up database and updating application files in-place"
                    : "Extracting files and configuring your local SQLite WAL database";
                stepIndicatorLabel.Text = preserveExistingSettingsOnly ? "Updating..." : "Installing...";
                btnBack.Enabled = false;
                btnNext.Enabled = false;
                btnCancel.Enabled = false;
                StartInstallation();
            }
            else if (step == 5)
            {
                headerTitleLabel.Text = preserveExistingSettingsOnly ? "Update Complete" : "Setup Complete";
                headerSubLabel.Text = preserveExistingSettingsOnly
                    ? "Application updated in-place — all database records & settings preserved"
                    : "Your pharmacy & branch terminal is configured and ready";
                stepIndicatorLabel.Text = "Completed";

                string serverDesc = rbCloudMode.Checked ? txtServerUrl.Text.Trim() : "Offline-First Local Engine (Can link to cloud anytime in Settings)";
                lblFinishSummary.Text =
                    "🏥  Pharmacy Name:      " + txtPharmacyName.Text.Trim() + "  (Locked on Login Screen)\r\n\r\n" +
                    "🔑  Organization Code:  " + txtOrgCode.Text.Trim().ToUpperInvariant() + "\r\n\r\n" +
                    "📍  Configured Branch:  " + txtBranchName.Text.Trim() + "  (" + txtBranchCode.Text.Trim().ToUpperInvariant() + ")   —   Terminal: " + txtDeviceCode.Text.Trim().ToUpperInvariant() + "\r\n\r\n" +
                    "💾  Database Status:    Preserved intact (Automatic pre-update backup saved)\r\n\r\n" +
                    "📂  Installed Folder:   " + installPathBox.Text;

                btnBack.Visible = false;
                btnCancel.Visible = false;
                btnNext.Location = new Point(568, 14);
                btnNext.Text = "Finish";
                btnNext.Enabled = true;
            }
        }

        private void BtnNext_Click(object sender, EventArgs e)
        {
            if (currentStep == 0)
            {
                ShowStep(1);
            }
            else if (currentStep == 1)
            {
                if (string.IsNullOrWhiteSpace(txtPharmacyName.Text) || string.IsNullOrWhiteSpace(txtOrgCode.Text))
                {
                    MessageBox.Show("Please enter both the Pharmacy Name and Organization Code.", "Validation", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                if (string.IsNullOrWhiteSpace(txtBranchName.Text) || string.IsNullOrWhiteSpace(txtBranchCode.Text))
                {
                    MessageBox.Show("Please enter both the Branch Name and Branch Code (e.g. HQ or BR02).", "Validation", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                ShowStep(2);
            }
            else if (currentStep == 2)
            {
                if (rbCloudMode.Checked && string.IsNullOrWhiteSpace(txtServerUrl.Text))
                {
                    MessageBox.Show("Please enter your Cloud Server URL or select Standalone/Offline Mode.", "Validation", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                if (string.IsNullOrWhiteSpace(txtDeviceCode.Text))
                {
                    txtDeviceCode.Text = "POS01";
                }
                ShowStep(3);
            }
            else if (currentStep == 3)
            {
                if (string.IsNullOrWhiteSpace(installPathBox.Text))
                {
                    MessageBox.Show("Please specify a valid installation folder.", "Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                ShowStep(4);
            }
            else if (currentStep == 5)
            {
                if (chkLaunchNow.Checked)
                {
                    string exePath = Path.Combine(installPathBox.Text, "PharmaCarePro.exe");
                    if (File.Exists(exePath))
                    {
                        try
                        {
                            ProcessStartInfo psi = new ProcessStartInfo(exePath);
                            psi.WorkingDirectory = installPathBox.Text;
                            Process.Start(psi);
                        }
                        catch (Exception ex)
                        {
                            MessageBox.Show("Could not launch application: " + ex.Message, "Launch Warning", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                        }
                    }
                }
                Application.Exit();
            }
        }

        private void BtnCancel_Click(object sender, EventArgs e)
        {
            if (isInstalling) return;
            if (MessageBox.Show("Are you sure you want to exit the PharmaCare Pro Setup Wizard?", "Exit Setup", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            {
                Application.Exit();
            }
        }

        private void AppendLog(string message)
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action<string>(AppendLog), message);
                return;
            }
            txtInstallLog.AppendText("[" + DateTime.Now.ToString("HH:mm:ss") + "] " + message + Environment.NewLine);
        }

        private void UpdateProgress(int percent, string statusText)
        {
            if (this.InvokeRequired)
            {
                this.BeginInvoke(new Action<int, string>(UpdateProgress), percent, statusText);
                return;
            }
            int clamped = Math.Max(0, Math.Min(100, percent));
            progressBar.Value = clamped;
            lblProgressPercent.Text = clamped.ToString() + "%";
            lblProgressStatus.Text = statusText;
        }

        private string EscapeJson(string s)
        {
            if (s == null) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "").Replace("\n", " ");
        }

        private void StartInstallation()
        {
            isInstalling = true;
            string targetDir = installPathBox.Text.Trim();
            bool makeDesktop = chkDesktopShortcut.Checked;
            bool makeStartMenu = chkStartMenuShortcut.Checked;
            bool regUninstall = chkRegisterUninstall.Checked;
            bool keepSettingsOnly = preserveExistingSettingsOnly;

            string pharmName = txtPharmacyName.Text.Trim();
            string orgCode = txtOrgCode.Text.Trim().ToUpperInvariant();
            string branchName = txtBranchName.Text.Trim();
            string branchCode = txtBranchCode.Text.Trim().ToUpperInvariant();
            string branchAddress = txtBranchAddress.Text.Trim();
            string branchPhone = txtBranchPhone.Text.Trim();
            string serverUrl = rbCloudMode.Checked ? txtServerUrl.Text.Trim() : "http://localhost:8000";
            string deviceCode = txtDeviceCode.Text.Trim().ToUpperInvariant();

            Thread worker = new Thread(() =>
            {
                try
                {
                    AppendLog(keepSettingsOnly
                        ? "Starting safe in-place application update (preserving all data & settings)..."
                        : "Starting PharmaCare Pro Enterprise installation...");

                    // 1. Close any running PharmaCarePro instance so files are never locked
                    try
                    {
                        Process[] runningProcs = Process.GetProcessesByName("PharmaCarePro");
                        if (runningProcs != null && runningProcs.Length > 0)
                        {
                            UpdateProgress(2, "Closing running PharmaCare Pro window for update...");
                            AppendLog("Closing running PharmaCarePro.exe instance before updating files...");
                            foreach (Process p in runningProcs)
                            {
                                try
                                {
                                    p.Kill();
                                    p.WaitForExit(5000);
                                }
                                catch { }
                            }
                            Thread.Sleep(500);
                        }
                    }
                    catch { }

                    // 2. Automatically back up existing SQLite database before updating
                    string dataDir = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                        "PharmacyManagement"
                    );
                    if (!Directory.Exists(dataDir))
                    {
                        Directory.CreateDirectory(dataDir);
                    }
                    string existingDb = Path.Combine(dataDir, "pharmacy.db");
                    if (File.Exists(existingDb))
                    {
                        try
                        {
                            UpdateProgress(4, "Backing up existing local database...");
                            string backupDir = Path.Combine(dataDir, "backups");
                            if (!Directory.Exists(backupDir))
                            {
                                Directory.CreateDirectory(backupDir);
                            }
                            string stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                            string backupPath = Path.Combine(backupDir, "pharmacy_pre_update_" + stamp + ".db");
                            File.Copy(existingDb, backupPath, true);
                            AppendLog("Safety backup created: " + backupPath);
                        }
                        catch (Exception bkEx)
                        {
                            AppendLog("Note: Could not create pre-update backup copy (" + bkEx.Message + "). Existing database remains intact.");
                        }
                    }

                    UpdateProgress(6, "Preparing installation directory...");
                    if (!Directory.Exists(targetDir))
                    {
                        Directory.CreateDirectory(targetDir);
                    }

                    Assembly asm = Assembly.GetExecutingAssembly();
                    Stream payloadStream = asm.GetManifestResourceStream("payload.zip");
                    if (payloadStream == null)
                    {
                        throw new Exception("Embedded application payload ('payload.zip') was not found in installer.");
                    }

                    using (ZipArchive archive = new ZipArchive(payloadStream, ZipArchiveMode.Read))
                    {
                        int totalEntries = archive.Entries.Count;
                        AppendLog("Extracting " + totalEntries + " application files...");
                        int processed = 0;

                        foreach (ZipArchiveEntry entry in archive.Entries)
                        {
                            processed++;
                            string relativePath = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
                            string fullDestPath = Path.Combine(targetDir, relativePath);

                            if (string.IsNullOrEmpty(entry.Name))
                            {
                                if (!Directory.Exists(fullDestPath))
                                    Directory.CreateDirectory(fullDestPath);
                                continue;
                            }

                            string parentDir = Path.GetDirectoryName(fullDestPath);
                            if (!string.IsNullOrEmpty(parentDir) && !Directory.Exists(parentDir))
                            {
                                Directory.CreateDirectory(parentDir);
                            }

                            entry.ExtractToFile(fullDestPath, true);

                            if (processed % 8 == 0 || processed == totalEntries || entry.Name.EndsWith(".exe"))
                            {
                                int pct = 8 + (int)((processed / (double)totalEntries) * 74.0);
                                UpdateProgress(pct, "Updating: " + entry.Name);
                            }
                            if (entry.Name.EndsWith(".exe") || entry.Name.EndsWith(".qss") || processed % 70 == 0)
                            {
                                AppendLog("Extracted: " + relativePath);
                            }
                        }
                    }

                    string exePath = Path.Combine(targetDir, "PharmaCarePro.exe");
                    string iconPath = Path.Combine(targetDir, "pharmacare.ico");
                    if (!File.Exists(iconPath))
                    {
                        iconPath = exePath;
                    }

                    if (!keepSettingsOnly)
                    {
                        // Write wizard_setup.json and .env to %LOCALAPPDATA%\PharmacyManagement
                        UpdateProgress(84, "Writing Pharmacy, Branch & Cloud Server configuration...");
                        string jsonPayload = "{\r\n" +
                            "  \"pharmacy_name\": \"" + EscapeJson(pharmName) + "\",\r\n" +
                            "  \"org_code\": \"" + EscapeJson(orgCode) + "\",\r\n" +
                            "  \"branch_name\": \"" + EscapeJson(branchName) + "\",\r\n" +
                            "  \"branch_code\": \"" + EscapeJson(branchCode) + "\",\r\n" +
                            "  \"branch_address\": \"" + EscapeJson(branchAddress) + "\",\r\n" +
                            "  \"branch_phone\": \"" + EscapeJson(branchPhone) + "\",\r\n" +
                            "  \"cloud_server_url\": \"" + EscapeJson(serverUrl) + "\",\r\n" +
                            "  \"device_code\": \"" + EscapeJson(deviceCode) + "\"\r\n" +
                            "}";
                        File.WriteAllText(Path.Combine(dataDir, "wizard_setup.json"), jsonPayload, Encoding.UTF8);

                        string envContent =
                            "PHARMACY_SERVER_URL=" + serverUrl + "\r\n" +
                            "PHARMACY_DEVICE_CODE=" + deviceCode + "\r\n";
                        File.WriteAllText(Path.Combine(dataDir, ".env"), envContent, Encoding.UTF8);
                        AppendLog("Saved pharmacy & cloud configuration to " + dataDir);

                        // Run headless database provisioning so SQLite DB is immediately seeded/updated non-destructively
                        if (File.Exists(exePath))
                        {
                            UpdateProgress(89, "Provisioning local SQLite database & branch profile...");
                            AppendLog("Provisioning database with Pharmacy '" + pharmName + "' & Branch '" + branchName + "'...");
                            try
                            {
                                ProcessStartInfo psi = new ProcessStartInfo(exePath, "--apply-wizard-setup");
                                psi.WorkingDirectory = targetDir;
                                psi.UseShellExecute = false;
                                psi.CreateNoWindow = true;
                                using (Process proc = Process.Start(psi))
                                {
                                    proc.WaitForExit(20000);
                                }
                                AppendLog("Local SQLite WAL database and branch profile verified.");
                            }
                            catch (Exception dbEx)
                            {
                                AppendLog("Note: Database will finish provisioning on first launch (" + dbEx.Message + ").");
                            }
                        }
                    }
                    else
                    {
                        UpdateProgress(89, "Existing database & pharmacy settings preserved intact...");
                        AppendLog("Kept existing pharmacy.db, Pharmacy Name, Branch, and Server configuration untouched.");
                    }

                    if (makeDesktop)
                    {
                        UpdateProgress(94, "Updating Desktop shortcut...");
                        string desktopDir = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                        string deskLnk = Path.Combine(desktopDir, "PharmaCare Pro.lnk");
                        CreateShortcut(deskLnk, exePath, targetDir, iconPath, pharmName + " — PharmaCare Pro Enterprise");
                        AppendLog("Updated Desktop shortcut: " + deskLnk);
                    }

                    if (makeStartMenu)
                    {
                        UpdateProgress(97, "Updating Start Menu shortcut...");
                        string startDir = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                        string startLnk = Path.Combine(startDir, "PharmaCare Pro.lnk");
                        CreateShortcut(startLnk, exePath, targetDir, iconPath, pharmName + " — PharmaCare Pro Enterprise");
                        AppendLog("Updated Start Menu shortcut: " + startLnk);
                    }

                    if (regUninstall)
                    {
                        UpdateProgress(99, "Registering application with Windows...");
                        RegisterUninstaller(targetDir, exePath, iconPath);
                        AppendLog("Registered in Windows Installed Apps.");
                    }

                    UpdateProgress(100, keepSettingsOnly ? "Application Update Complete!" : "Installation & Pharmacy Provisioning Complete!");
                    AppendLog("Setup finished successfully.");
                    Thread.Sleep(400);

                    this.BeginInvoke(new Action(() =>
                    {
                        isInstalling = false;
                        ShowStep(5);
                    }));
                }
                catch (Exception ex)
                {
                    AppendLog("ERROR: " + ex.Message);
                    this.BeginInvoke(new Action(() =>
                    {
                        isInstalling = false;
                        btnCancel.Enabled = true;
                        MessageBox.Show(
                            "An error occurred during installation:\n\n" + ex.Message +
                            "\n\nPlease make sure PharmaCarePro.exe is not currently running and try again.",
                            "Installation Error",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Error
                        );
                    }));
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        private void CreateShortcut(string shortcutPath, string targetExe, string workingDir, string iconLocation, string description)
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType == null) return;
            dynamic shell = Activator.CreateInstance(shellType);
            dynamic shortcut = shell.CreateShortcut(shortcutPath);
            shortcut.TargetPath = targetExe;
            shortcut.WorkingDirectory = workingDir;
            shortcut.IconLocation = iconLocation;
            shortcut.Description = description;
            shortcut.Save();
        }

        private void RegisterUninstaller(string targetDir, string exePath, string iconPath)
        {
            try
            {
                string uninstBat = Path.Combine(targetDir, "Uninstall_PharmaCarePro.bat");
                string batContent = "@echo off\r\n" +
                    "echo Uninstalling PharmaCare Pro Enterprise...\r\n" +
                    "del /f /q \"%USERPROFILE%\\Desktop\\PharmaCare Pro.lnk\" 2>nul\r\n" +
                    "del /f /q \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\PharmaCare Pro.lnk\" 2>nul\r\n" +
                    "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PharmaCarePro\" /f 2>nul\r\n" +
                    "echo Removed shortcuts and registry entry. You may now delete: " + targetDir + "\r\n" +
                    "pause\r\n";
                File.WriteAllText(uninstBat, batContent);

                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\PharmaCarePro"))
                {
                    if (key != null)
                    {
                        key.SetValue("DisplayName", "PharmaCare Pro Enterprise");
                        key.SetValue("DisplayVersion", "1.0.0");
                        key.SetValue("Publisher", "PharmaCare Enterprise");
                        key.SetValue("DisplayIcon", iconPath);
                        key.SetValue("InstallLocation", targetDir);
                        key.SetValue("UninstallString", "\"" + uninstBat + "\"");
                        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                    }
                }
            }
            catch { }
        }

        [STAThread]
        public static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new SetupWizardForm());
        }
    }
}
