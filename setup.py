from setuptools import setup, find_packages 

with open("README.md", "r",encoding="utf8") as readme_file:
    readme = readme_file.read()

requirements = ["playwright","aioconsole"] 

setup(
    name="ChatGPTWeb",
    version="0.0.9",
    author="nek0us",
    author_email="nekouss@gmail.com",
    description="a ChatGPT API,no web ui",
    long_description=readme,
    long_description_content_type="text/markdown",
    url="https://github.com/nek0us/ChatGPT",
    packages=find_packages(),
    install_requires=requirements,
    classifiers=[
	"Programming Language :: Python :: 3.9",
	"License :: OSI Approved :: MIT License",
    ],
)