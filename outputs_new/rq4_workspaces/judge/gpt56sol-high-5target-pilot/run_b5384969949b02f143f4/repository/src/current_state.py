# Generated current behavior. Edit this module to implement requested changes.
PROJECT = {'artifact_class': 'SAAS_WEB_APPLICATION',
 'description': 'Offline executable SaaS website with current landing, shared-site, access, '
                'provisioning, and admin-workspace behavior.',
 'primary_artifacts': ['dist/index.html', 'dist/catalog.json'],
 'project_id': '43772711',
 'renderer': 'web',
 'title': '43772711'}

FEATURES = [{'attributes': {'brand_alignment': 'Translate the current brand styles to the SaaS UI.',
                 'design_objective': 'Confirm the layout and style of the UI shell.',
                 'visual_quality_benchmark': 'Equal or exceed the quality of the attached Google '
                                             'Workspace UI example.'},
  'components': ['UI_UX', 'FRONTEND'],
  'contexts': ['ADMIN_WORKSPACE', 'UI_SHELL'],
  'execution': {},
  'lifecycle': 'ACTIVE',
  'slug': 'admin-workspace-shell-styling',
  'title': 'Admin Workspace Shell Styling'},
 {'attributes': {'sign_up_button_required': True},
  'components': ['FRONTEND', 'UI_UX'],
  'contexts': ['LANDING_PAGE'],
  'execution': {},
  'lifecycle': 'ACTIVE',
  'slug': 'landing-page-sign-up-call-to-action',
  'title': 'Landing-Page Sign-Up Call to Action'}]
