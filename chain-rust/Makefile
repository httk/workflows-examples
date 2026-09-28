# `httk workflow build` exports HTTK_WORKFLOW_LANGUAGES_DIR, the installed native SDK directory.
ifndef HTTK_WORKFLOW_LANGUAGES_DIR
$(error HTTK_WORKFLOW_LANGUAGES_DIR is not set; build with `httk workflow build` or set it to the installed httk/workflow/languages)
endif
SDK := $(HTTK_WORKFLOW_LANGUAGES_DIR)

# Cargo cannot expand environment variables in a path dependency, so the
# installed SDK crate is copied to target/sdk, which Cargo.toml depends on.
# target/ is a declared build artifact, so the copy never enters the source
# digest. The crate is std-only: the offline build needs no network. The cargo
# tree is removed after the build, so a registration holds only the binary.
chain: src/main.rs Cargo.toml $(SDK)/rust/Cargo.toml $(SDK)/rust/src/lib.rs
	rm -rf target/sdk
	mkdir -p target
	cp -R $(SDK)/rust target/sdk
	chmod -R u+w target/sdk
	cargo build --release --offline
	cp target/release/chain chain
	rm -rf target Cargo.lock

clean:
	rm -rf target chain Cargo.lock
