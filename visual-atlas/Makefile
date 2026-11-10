# Visual Atlas: build, test and theme tasks.
# Inside the Docker image:   make all
# From the host:             make image  &&  make docker-all   (or docker-build, docker-test, ...)
IMAGE ?= visual-atlas

.PHONY: all build test themes gallery report clean image shell
all: build themes test report

build:          ## package both visuals into release/
	bash scripts/build.sh
test:           ## render all test cases in the mock host and run the checks
	bash scripts/test.sh
themes:         ## regenerate and validate the report themes
	bash scripts/themes.sh
report:         ## Power BI project (.pbip) with every Atlas visual on ready-made pages
	python3 tools/mk_report.py
	cd release && rm -f VisualAtlasTest.zip && python3 -c "import shutil; shutil.make_archive('VisualAtlasTest', 'zip', 'report')"
gallery:        ## rebuild the gallery HTML page
	bash scripts/gallery.sh
clean:
	rm -rf visuals/*/dist visuals/*/.tmp visuals/*/webpack.statistics.*.html visuals/test/out

image:          ## build the Docker image
	docker build -t $(IMAGE) -f docker/Dockerfile .
shell:          ## open a shell in the image with this folder mounted
	docker run --rm -it -v "$(CURDIR)":/work -w /work $(IMAGE) bash
docker-%:       ## run any target inside the image, e.g. make docker-test
	docker run --rm -v "$(CURDIR)":/work -w /work $(IMAGE) make $*
