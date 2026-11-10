# Office Hub systemd services

Production and staging run Celery workers and Celery beat as separate services. Workers never use `-B`. Each environment has exactly one named beat unit and a distinct pidfile/state directory, so systemd cannot start a second instance of that environment's scheduler.

Install production worker services after the maintenance branch is merged into `/home/officehub/office-hub`:

```sh
sudo install -m 0644 deploy/officehub-worker.service deploy/officehub-beat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now officehub-worker officehub-beat
```

Install staging services from `/home/officehub/office-hub-maint`:

```sh
sudo install -m 0644 deploy/officehub-staging-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now officehub-staging-backend officehub-staging-frontend officehub-staging-worker officehub-staging-beat
```

The staging environment file is `/home/officehub/office-hub-maint/.env.staging`; it is intentionally ignored by Git.

If system-level installation is awaiting sudo access, the server's `officehub` user has lingering enabled. The equivalent staging-only units under `deploy/user/` can be installed into `/home/officehub/.config/systemd/user/` and enabled with `systemctl --user enable --now ...`. Production continues to use the system-level units so `deploy.sh` can fail loudly through `sudo systemctl`.
