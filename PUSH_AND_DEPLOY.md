# Push to GitHub, then deploy on Render

## 1. Push (for whoever has write access to the repository)

The target repository is empty: https://github.com/siddiquaadeena504-max/ForgeSight.git
Push the contents of this folder (the folder that contains this file) to branch `main`. Keep every file, including
`data/models/**/model.pt` and `data/weights/*.pth` (trained models, about 50 MB in total, no file over 20 MB) -
the app cannot detect anything without them. Do not add `node_modules`, `.next` or `data/storage`.

    git init -b main
    git add -A
    git commit -m "ForgeSight inspection platform"
    git remote add origin https://github.com/siddiquaadeena504-max/ForgeSight.git
    git push -u origin main

Check afterwards that GitHub shows the folders `backend`, `frontend`, `data`, `docs`, `scripts` and the file `render.yaml`.

## 2. Deploy on Render

1. Render dashboard > New > Blueprint > connect the GitHub repository. Render reads `render.yaml`.
2. Enter a value for `FS_ADMIN_PASSWORD` (10+ characters) when asked. That is the login password.
3. Apply. Render creates the database, the engine (private) and the web UI (public).
4. Open the URL of `forgesight-web` and sign in as `admin@forgesight.local` with that password.

Known risks on the first deploy (none of this has been run on Render yet):
* The Docker images have never been built. If a build fails, the build log names the failing step.
* The web UI reads the engine address at build time. If the UI loads but login fails, redeploy `forgesight-web`
  after `forgesight-engine` is live.
* If the engine cannot run as a private service on your plan, change `type: pserv` to `type: web`, and set
  `BACKEND_URL` on the web service to the engine's public URL instead of `BACKEND_HOSTPORT`.
* The engine and its disk are paid plans; the free tier does not have enough memory for PyTorch.
